#!/usr/bin/env python3
"""Real SSE probes for staggered arrivals and repeated coding conversations.

Run against an idle, dedicated server. Full elapsed times include prefill; SSE
gaps are visible chunk gaps, not token-level kernel timings. No model tools run.
"""

import argparse
import concurrent.futures
import json
import math
import threading
import time
import urllib.request
from pathlib import Path


def get(base, route):
    with urllib.request.urlopen(base + route, timeout=10) as response:
        return json.load(response)


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else 0


def stream(base, model, messages, tokens, index, gate=None, signal=None, fixed=True,
           reasoning_effort="medium"):
    payload = dict(model=model, messages=messages, stream=True,
                   stream_options={"include_usage": True}, temperature=0,
                   max_tokens=tokens, reasoning_effort=reasoning_effort)
    if fixed:
        payload["ignore_eos"] = True
    if gate is not None and not gate.wait(120):
        raise RuntimeError("First stream did not produce output within 120 seconds")
    request = urllib.request.Request(base + "/v1/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    started = time.monotonic()
    events, content, usage, finish, done = [], [], {}, None, False
    with urllib.request.urlopen(request, timeout=900) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                done = True
                break
            item = json.loads(raw)
            if item.get("error"):
                raise RuntimeError(str(item["error"]))
            if item.get("usage"):
                usage = item["usage"]
            for choice in item.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content") or delta.get("reasoning_content"):
                    events.append(time.monotonic())
                    if signal is not None:
                        signal.set()
                content.append(delta.get("content") or "")
                finish = choice.get("finish_reason") or finish
    ended = time.monotonic()
    if not done or not finish or not events or not usage.get("completion_tokens"):
        raise RuntimeError("Incomplete SSE stream or missing usage")
    if fixed and usage["completion_tokens"] != tokens:
        raise RuntimeError("Fixed-output probe did not produce requested token count")
    gaps = [right - left for left, right in zip(events, events[1:])]
    return dict(id=index, start=started, end=ended, first=events[0], last=events[-1],
                elapsed_s=ended-started, ttft_s=events[0]-started,
                gap_p95_s=percentile(gaps, .95), gap_p99_s=percentile(gaps, .99),
                gap_max_s=max(gaps, default=0), events=events, usage=usage,
                cached_prompt_tokens=usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                content="".join(content), finish=finish, done=done)


def probe(args, count, iteration):
    before = get(args.base, "/v1/stats")
    if before["requests"]["active"]:
        raise RuntimeError("Server has existing work; refusing to mix measurements")
    nonce = str(time.time_ns())
    rounds = []
    if args.mode == "staggered":
        first = threading.Event()
        pads = [1024] + [98304 // (count - 1)] * (count - 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            futures = []
            for index, pad in enumerate(pads):
                prompt = (f"Probe {nonce} session {index}.\n" + " test" * pad +
                          "\nExplain a robust Python queue with cancellation, resource "
                          "ownership and timeouts. Include implementation and tests.")
                futures.append(pool.submit(stream, args.base, args.model,
                    [{"role": "user", "content": prompt}], 512 if index == 0 else 256,
                    index, None if index == 0 else first, first if index == 0 else None))
            rounds.append([future.result() for future in futures])
    else:
        histories = []
        expected = []
        for index in range(count):
            marker = f"VIOLET_{index}_{nonce}"
            expected.append({"marker": marker, "sum": 45})
            prompt = ("Reference record: " + json.dumps(expected[-1]) + "\n" + " test" * 16384 +
                      "\nReturn only the reference JSON record from the beginning. No Markdown.")
            histories.append([{"role": "user", "content": prompt}])
        for turn in range(2):
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                futures = [pool.submit(stream, args.base, args.model, messages,
                                       512, index, fixed=False)
                           for index, messages in enumerate(histories)]
                rows = [future.result() for future in futures]
            for row, messages, wanted in zip(rows, histories, expected):
                try:
                    row["quality_ok"] = json.loads(row["content"].strip()) == wanted
                except ValueError:
                    row["quality_ok"] = False
                messages.extend([{"role": "assistant", "content": row["content"]},
                                 {"role": "user", "content": "Return that same JSON record again exactly."}])
            rounds.append(rows)
    after = get(args.base, "/v1/stats")
    rows = [row for group in rounds for row in group]
    counters_ok = (after["instance_id"] == before["instance_id"] and
                   after["requests"]["active"] == 0 and
                   after["requests"]["completed"] - before["requests"]["completed"] == len(rows) and
                   after["requests"]["completion_tokens_total"] - before["requests"]["completion_tokens_total"] ==
                   sum(row["usage"]["completion_tokens"] for row in rows))
    report = dict(profile=args.profile, mode=args.mode, concurrency=count, iteration=iteration,
                  rounds=rounds, before=before, after=after, counters_ok=counters_ok)
    if args.mode == "warm":
        report["followup_prefix_reuse_observed"] = all(row["cached_prompt_tokens"] > 0 for row in rounds[1])
    path = Path(args.out) / f"{args.profile}-{args.mode}-c{count}-r{iteration}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(path=str(path), counters_ok=counters_ok, rounds=[[
        {key: row[key] for key in ("id", "ttft_s", "elapsed_s", "gap_max_s", "cached_prompt_tokens")}
        for row in group] for group in rounds])), flush=True)
    if not counters_ok or any(row.get("quality_ok") is False for row in rows):
        raise RuntimeError("Accounting or JSON isolation verification failed; see saved report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:1919")
    parser.add_argument("--model", default="qwen38-flash-next")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("staggered", "warm"), required=True)
    parser.add_argument("--counts", default="2,3")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    counts = [int(value) for value in args.counts.split(",")]
    if args.repeats < 1 or any(count < 2 for count in counts):
        parser.error("Need positive repeats and at least two simultaneous requests")
    for iteration in range(1, args.repeats + 1):
        for count in counts:
            probe(args, count, iteration)


if __name__ == "__main__":
    main()
