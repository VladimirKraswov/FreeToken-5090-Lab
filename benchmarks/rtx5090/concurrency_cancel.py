"""Disconnect an unfinished prefill while an already streaming request survives.

Run on the server host against an idle HTTP localhost origin with readable systemd
logs. A completed partial-prefill log establishes the victim's phase; this does
not claim to interrupt a GPU kernel already executing when the socket closes.
"""

import argparse
import concurrent.futures
import http.client
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from concurrency_latency import get, stream


PREFILL = re.compile(
    r"Prefill batch, .*#new-token: (\d+), .*#running-req: (\d+), #queue-req: (\d+)"
)


def journal(unit, since):
    raw = subprocess.check_output(
        ["journalctl", "-u", unit, "--since", f"@{since:.6f}", "--no-pager", "-o", "json"],
        text=True, timeout=10,
    )
    entries = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
            stamp = int(record["__MONOTONIC_TIMESTAMP"]) / 1e6
            message = record.get("MESSAGE", "")
            if isinstance(message, list):
                message = bytes(message).decode("utf-8", "replace")
            if isinstance(message, str):
                entries.append({"t": stamp, "message": message})
        except (ValueError, TypeError, KeyError):
            continue
    return entries


def partial_prefill(entries, started):
    latest = None
    for entry in entries:
        match = PREFILL.search(entry["message"])
        if entry["t"] >= started and match:
            new_tokens, running, queued = map(int, match.groups())
            latest = dict(entry, new_tokens=new_tokens, running=running, queued=queued)
    if latest and latest["new_tokens"] > 0 and latest["running"] == 1 and latest["queued"] == 1:
        return latest
    return None


def read_request_id(response):
    while True:
        line = response.readline()
        if not line:
            raise RuntimeError("Victim stream ended before its initial role event")
        if not line.startswith(b"data:"):
            continue
        item = json.loads(line[5:].strip())
        if item.get("error"):
            raise RuntimeError(str(item["error"]))
        match = re.fullmatch(r"chatcmpl-(\d+)", item.get("id", ""))
        if not match:
            raise RuntimeError("Victim initial SSE event has no numeric request ID")
        if any(choice.get("delta", {}).get(key) for choice in item.get("choices", [])
               for key in ("content", "reasoning_content")):
            raise RuntimeError("Victim already produced output before phase observation")
        return int(match.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:1919")
    parser.add_argument("--model", default="qwen38-flash-next")
    parser.add_argument("--out", required=True)
    parser.add_argument("--journal-unit", default="freetoken-qwen.service")
    args = parser.parse_args()
    url = urlsplit(args.base)
    if (url.scheme != "http" or url.path not in ("", "/") or
            url.hostname not in ("127.0.0.1", "localhost", "::1")):
        parser.error("Run this journal-backed probe on the server host against HTTP localhost")
    before = get(args.base, "/v1/stats")
    if before["requests"]["active"]:
        raise RuntimeError("Server has existing work")
    since = time.time()
    journal(args.journal_unit, since)
    nonce = str(time.time_ns())
    survivor_first = threading.Event()
    survivor_finished = threading.Event()
    expected = {"marker": "SURVIVE_" + nonce, "values": list(range(256)), "sum": 45}

    def survive():
        try:
            prompt = (json.dumps(expected) + "\n" + " test" * 1024 +
                      "\nReturn only the complete exact JSON record from the beginning. "
                      "Copy every value, no Markdown.")
            row = stream(args.base, args.model, [{"role": "user", "content": prompt}],
                         3072, 1, signal=survivor_first, fixed=False, reasoning_effort="off")
            row["quality_ok"] = json.loads(row["content"].strip()) == expected
            return row
        except Exception as error:
            return {"error": str(error), "quality_ok": False}
        finally:
            survivor_finished.set()

    def cancel():
        row = {}
        connection = None
        response = None
        try:
            if not survivor_first.wait(120) or survivor_finished.is_set():
                raise RuntimeError("Survivor did not remain streaming before victim admission")
            payload = dict(model=args.model, messages=[{"role": "user", "content":
                "Cancel probe " + nonce + "\n" + " test" * 98304 +
                "\nExplain Python task queues and cancellation in detail."}],
                max_tokens=2048, stream=True, ignore_eos=True, temperature=0,
                reasoning_effort="medium")
            connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=120)
            row["start"] = time.monotonic()
            connection.request("POST", "/v1/chat/completions", json.dumps(payload),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP status {response.status}")
            row["uid"] = read_request_id(response)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if survivor_finished.is_set():
                    raise RuntimeError("Survivor finished before an incomplete victim prefill was observed")
                evidence = partial_prefill(journal(args.journal_unit, since), row["start"])
                if evidence:
                    snapshot = get(args.base, "/v1/stats")
                    if snapshot["requests"]["active"] == 2 and not survivor_finished.is_set():
                        row["partial_prefill"] = evidence
                        row["stats_before_close"] = snapshot
                        break
                time.sleep(.2)
            else:
                raise RuntimeError("No partial prefill with one running and one queued request observed")
        except Exception as error:
            row["error"] = str(error)
        finally:
            row["close_begin"] = time.monotonic()
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()
            row["closed"] = time.monotonic()
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        survivor_future = pool.submit(survive)
        cancelled_future = pool.submit(cancel)
        cancelled, survivor = cancelled_future.result(), survivor_future.result()
    deadline = time.monotonic() + 60
    after = get(args.base, "/v1/stats")
    while after["requests"]["active"] and time.monotonic() < deadline:
        time.sleep(.5)
        after = get(args.base, "/v1/stats")
    entries = journal(args.journal_unit, since)
    uid = cancelled.get("uid")
    abort_pattern = re.compile(rf"Aborting request for user {uid}(?!\d)")
    aborts = [entry for entry in entries if entry["t"] >= cancelled["close_begin"] and
              uid is not None and abort_pattern.search(entry["message"])]
    deltas = {key: after["requests"][key] - before["requests"][key]
              for key in ("completed", "prompt_tokens_total", "completion_tokens_total")}
    usage = survivor.get("usage", {})
    at_close = cancelled.get("stats_before_close", {}).get("requests", {})
    victim_prompt_tokens = (at_close.get("prompt_tokens_total", 0) -
                            before["requests"]["prompt_tokens_total"] - usage.get("prompt_tokens", 0))
    checks = {
        "no_probe_errors": "error" not in cancelled and "error" not in survivor,
        "partial_prefill_observed": bool(cancelled.get("partial_prefill")),
        "both_active_at_close": at_close.get("active") == 2,
        "survivor_spans_close": (survivor.get("first", float("inf")) < cancelled["close_begin"] and
                                 cancelled["closed"] < survivor.get("end", 0)),
        "survivor_exact_json": survivor.get("quality_ok", False),
        "victim_abort_logged_once": len(aborts) == 1,
        "exactly_one_completed": deltas["completed"] == 1,
        "only_survivor_generated_tokens": deltas["completion_tokens_total"] == usage.get("completion_tokens"),
        "both_prompts_admitted_once": (victim_prompt_tokens > cancelled.get("partial_prefill", {}).get("new_tokens", 0) and
                                       deltas["prompt_tokens_total"] == victim_prompt_tokens + usage.get("prompt_tokens", 0)),
        "terminal_idle": after["requests"]["active"] == 0 and after["mamba"]["used_slots"] == 0,
        "same_instance": before["instance_id"] == after["instance_id"],
        "healthy": get(args.base, "/health")["status"] == "ok",
    }
    passed = all(checks.values())
    report = dict(before=before, cancelled=cancelled, survivor=survivor, after=after,
                  expected_survivor=expected, checks=checks, passed=passed,
                  counter_deltas=deltas, victim_prompt_tokens=victim_prompt_tokens,
                  victim_abort_journal=aborts, journal_unit=args.journal_unit,
                  abort_accounting="No public aborted counter: require one victim-specific abort log, "
                                   "two admitted prompts, one completed request and terminal idle state.")
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"passed": passed, "checks": checks, "counter_deltas": deltas,
                      "survivor_elapsed_s": survivor.get("elapsed_s")}), flush=True)
    if not passed:
        raise RuntimeError("Cancellation/isolation failed; see saved report")


if __name__ == "__main__":
    main()
