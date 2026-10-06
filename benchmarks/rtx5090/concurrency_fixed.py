"""Matched cold prompts across profiles; use the same seed and repeat after each restart.

The prompt marker includes padding, concurrency, request ID and repeat, never the
profile. Keep --enable-cache-report enabled to interpret zero cached-token usage.
"""

import argparse
import concurrent.futures
import hashlib
import json
import threading
import time
import urllib.request
from pathlib import Path


def get(base, route):
    with urllib.request.urlopen(base + route, timeout=10) as response:
        return json.load(response)


def corpus_identity(seed, repeat, pad, count, quality):
    key = json.dumps(
        {"seed": seed, "repeat": repeat, "padding": pad, "concurrency": count, "quality": quality},
        sort_keys=True, separators=(",", ":"),
    )
    return key, hashlib.sha256(key.encode()).hexdigest()[:20]


def build_payload(index, pad, nonce, tokens, quality=False):
    marker = "SESSION_" + str(index) + "_" + nonce
    prompt = (
        f"{marker}\nReference data follows.\n" + " test" * pad +
        "\nIgnore the padding. Explain a safe design for a Python asynchronous task queue: "
        "cancellation, timeouts, independent request state and error handling. "
        "Include a concise implementation example."
    )
    if quality:
        prompt = (
            "Reference record: " + json.dumps({"marker": marker, "needle": f"VIOLET_{index}"}) +
            "\n" + " test" * pad +
            "\nUse the reference record at the beginning. Return only a JSON object with keys "
            "marker, sum, needle. sum must equal 17+28. Copy marker and needle from that record "
            "exactly. Do not include Markdown."
        )
    # Keep field order and default JSON serialization stable for matched payload hashes.
    payload = {
        "model": "qwen38-flash-next",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0,
        "max_tokens": 512 if quality else tokens,
        "reasoning_effort": "medium",
    }
    if not quality:
        payload["ignore_eos"] = True
    return payload, marker


def one(base, tokens, index, barrier, pad, nonce, quality=False):
    payload, marker = build_payload(index, pad, nonce, tokens, quality)
    prompt = payload["messages"][0]["content"]
    encoded = json.dumps(payload).encode()
    payload_hash = hashlib.sha256(encoded).hexdigest()
    request = urllib.request.Request(base + "/v1/chat/completions", data=encoded,
                                     headers={"Content-Type": "application/json"})
    barrier.wait()
    start = time.monotonic()
    events, parts, reason, usage = [], [], [], {}
    done, finish = False, None
    try:
        with urllib.request.urlopen(request, timeout=1200) as response:
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
                    text = (delta.get("reasoning_content") or "") + (delta.get("content") or "")
                    if text:
                        events.append(time.monotonic())
                        parts.append(delta.get("content") or "")
                        reason.append(delta.get("reasoning_content") or "")
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        end = time.monotonic()
        count = usage.get("completion_tokens", 0)
        assert done and finish and count > 0 and events, "incomplete stream"
        content = "".join(parts)
        row = {
            "id": index, "start": start, "end": end, "first": events[0], "last": events[-1],
            "elapsed_s": end-start, "ttft_s": events[0]-start, "usage": usage,
            "decode_tps": ((count-1)/(events[-1]-events[0])
                           if len(events) > 1 and events[-1] > events[0] else None),
            "end_to_end_tps": count/(end-start), "finish": finish, "done": done,
            "content": content, "reasoning_sha256": hashlib.sha256("".join(reason).encode()).hexdigest(),
            "max_nonempty_chunk_gap_s": max((right-left for left, right in zip(events, events[1:])), default=0),
            "payload_sha256": payload_hash, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_characters": len(prompt), "marker": marker,
            "cached_prompt_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
        }
        row["fixed_output_ok"] = quality or (count == tokens and finish == "length")
        if quality:
            try:
                row["quality_ok"] = json.loads(content.strip()) == {
                    "marker": marker, "sum": 45, "needle": f"VIOLET_{index}",
                }
            except Exception:
                row["quality_ok"] = False
        return row
    except Exception as error:
        return {
            "id": index, "start": start, "end": time.monotonic(), "error": str(error),
            "payload_sha256": payload_hash, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "marker": marker,
        }


def monitor_stats(base, samples, stop):
    while not stop.is_set():
        try:
            poll_start = time.monotonic()
            snapshot = get(base, "/v1/stats")
            samples.append({"t": time.monotonic(), "active": snapshot["requests"]["active"],
                            "kv": snapshot.get("kv"), "mamba": snapshot.get("mamba"),
                            "vram": snapshot.get("vram_bytes"),
                            "poll_start": poll_start, "poll_end": time.monotonic(),
                            "requests": snapshot["requests"],
                            "instance_id": snapshot.get("instance_id")})
        except Exception as error:
            samples.append({"error": str(error)})
        stop.wait(.5)



def steady_generation(samples, before, rows):
    """Counter rate while every prompt is consumed and every request is unfinished.

    Discard five seconds after every stream first delivers nonempty output. Use a
    contiguous window with <=3s HTTP poll latency and <=5s between samples.
    This is aggregate frontend token accounting, independent of SSE text chunks.
    """
    if not rows or any("error" in row for row in rows):
        return None
    initial = before["requests"]
    prompt_total = initial["prompt_tokens_total"] + sum(row["usage"]["prompt_tokens"] for row in rows)
    count = len(rows)
    first_ready = max(row["first"] for row in rows)
    groups, current = [], []
    for sample in samples:
        requests = sample.get("requests", {})
        valid = (sample.get("instance_id") == before["instance_id"] and
                 requests.get("active") == count and
                 requests.get("completed") == initial["completed"] and
                 requests.get("prompt_tokens_total") == prompt_total and
                 0 <= sample.get("poll_end", 0) - sample.get("poll_start", -2) <= 3)
        valid = valid and sample["t"] >= first_ready + 5
        if not valid or (current and sample["t"] - current[-1]["t"] > 5):
            if current:
                groups.append(current)
                current = []
        if valid:
            current.append(sample)
    if current:
        groups.append(current)
    if not groups:
        return None
    window = max(groups, key=lambda group: group[-1]["t"] - group[0]["t"])
    left, right = window[0], window[-1]
    span = right["t"] - left["t"]
    delta = right["requests"]["completion_tokens_total"] - left["requests"]["completion_tokens_total"]
    if span < 5 or delta < 32 or any(
            b["requests"]["completion_tokens_total"] < a["requests"]["completion_tokens_total"]
            for a, b in zip(window, window[1:])):
        return None
    return {"elapsed_s": span, "completion_tokens": delta, "aggregate_tps": delta / span,
            "per_active_request_tps": delta / span / count, "active_requests": count,
            "first_sample": left, "last_sample": right, "samples": len(window),
            "warmup_excluded_s": 5, "max_poll_latency_s": 3, "max_sample_gap_s": 5,
            "aggregate_tps_lower_bound": delta / (right["poll_end"] - left["poll_start"]),
            "aggregate_tps_upper_bound": (delta / (right["poll_start"] - left["poll_end"])
                                           if right["poll_start"] > left["poll_end"] else None)}


def run_wave(args, pad, count):
    before = get(args.base, "/v1/stats")
    if before["requests"]["active"]:
        raise RuntimeError("Existing active requests; refusing to mix benchmark with owner work")
    corpus_key, nonce = corpus_identity(args.corpus_seed, args.repeat, pad, count, args.quality)
    barrier = threading.Barrier(count)
    started = time.monotonic()
    samples, stop = [], threading.Event()
    monitor = threading.Thread(target=monitor_stats, args=(args.base, samples, stop), daemon=True)
    monitor.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        rows = list(pool.map(lambda index: one(args.base, args.tokens, index, barrier, pad,
                                               nonce, args.quality), range(count)))
    stop.set()
    monitor.join(11)
    finished = time.monotonic()
    good = [row for row in rows if "error" not in row]
    peak = max((sum(row["first"] <= sample["t"] <= row["last"] for row in good)
                for sample in samples if "t" in sample), default=0)
    report = {
        "profile": args.profile, "padding_requested": pad, "concurrency": count,
        "quality": args.quality, "rows": rows, "total_elapsed_s": finished-started,
        "aggregate_end_to_end_tps": (
            sum(row["usage"]["completion_tokens"] for row in good) /
            (max(row["end"] for row in good) - min(row["start"] for row in good)) if good else 0
        ),
        "overlapping_stream_windows_peak": peak, "samples": samples,
        "before": before, "after": get(args.base, "/v1/stats"),
    }
    after = report["after"]
    report["steady_generation"] = steady_generation(samples, before, rows)
    tokens = sum(row["usage"]["completion_tokens"] for row in good)
    prompts = sum(row["usage"]["prompt_tokens"] for row in good)
    counters_ok = (
        before["instance_id"] == after["instance_id"] and after["requests"]["active"] == 0 and
        after["requests"]["completed"] - before["requests"]["completed"] == count and
        after["requests"]["completion_tokens_total"] - before["requests"]["completion_tokens_total"] == tokens and
        after["requests"]["prompt_tokens_total"] - before["requests"]["prompt_tokens_total"] == prompts
    )
    cold_usage_ok = len(good) == count and all(row["cached_prompt_tokens"] == 0 for row in good)
    report.update(
        corpus_seed=args.corpus_seed, corpus_repeat=args.repeat, corpus_key=corpus_key,
        corpus_nonce=nonce, corpus_version=1, counters_ok=counters_ok, cold_usage_ok=cold_usage_ok,
        requested_output_tokens=512 if args.quality else args.tokens,
        cache_report_requirement="Server must enable --enable-cache-report; absent/zero usage alone "
                                 "cannot establish that reporting is enabled.",
    )
    path = Path(args.out) / f"{args.profile}-p{pad}-c{count}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("rows", "samples", "before", "after")}), flush=True)
    print(json.dumps([
        {"id": row["id"], "ttft_s": row.get("ttft_s"), "decode_tps": row.get("decode_tps"),
         "error": row.get("error"), "quality_ok": row.get("quality_ok")}
        for row in rows
    ]), flush=True)
    if (len(good) != count or not counters_ok or not cold_usage_ok or
            (getattr(args, "require_steady", False) and report["steady_generation"] is None) or
            any(not row["fixed_output_ok"] or row.get("quality_ok") is False for row in good)):
        raise RuntimeError("Benchmark completion, accounting, cold usage or quality check failed; stop further requests")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:1919")
    parser.add_argument("--lengths", default="1024,16384")
    parser.add_argument("--counts", default="1,2,3")
    parser.add_argument("--tokens", type=int, default=256)
    parser.add_argument("--quality", action="store_true")
    parser.add_argument("--require-steady", action="store_true", help="Require a valid post-prefill counter window")
    parser.add_argument("--corpus-seed", required=True)
    parser.add_argument("--repeat", type=int, required=True)
    args = parser.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    if args.repeat < 1 or args.tokens < 1:
        parser.error("--repeat and --tokens must be positive")
    for pad in map(int, args.lengths.split(",")):
        for count in map(int, args.counts.split(",")):
            run_wave(args, pad, count)


if __name__ == "__main__":
    main()
