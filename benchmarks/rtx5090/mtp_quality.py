"""Small, verifiable HTTP correctness smoke suite for an MTP A/B run.

Set FT_BASE, FT_MODEL, FT_API_KEY and FT_VALIDATION_OUT as needed. Run the
same file against both configurations. No model-generated code is executed.
This is a regression screen, not evidence of general model-quality parity.
The 420-second suite budget is an operational limit, not a speed threshold.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def cases():
    source = {
        "cluster": "atlas",
        "workers": [
            {"name": "alpha", "port": 8420, "retries": 3, "path": "/srv/v1/alpha"},
            {"name": "beta", "port": 8421, "retries": 3, "path": "/srv/v1/beta"},
            {"name": "gamma", "port": 8422, "retries": 3, "path": "/srv/v1/gamma"},
            {"name": "omega", "port": 8423, "retries": 3, "path": "/srv/v1/omega"},
        ],
        "archive": "/srv/v1-backup",
    }
    expected = {
        "cluster": "lyra",
        "workers": [
            {"name": "alpha", "port": 8420, "retries": 3, "path": "/srv/v2/alpha"},
            {"name": "delta", "port": 9521, "retries": 7, "path": "/srv/v2/delta"},
            {"name": "gamma", "port": 8422, "retries": 3, "path": "/srv/v2/gamma"},
            {"name": "omega", "port": 8423, "retries": 3, "path": "/srv/v2/omega"},
        ],
        "archive": "/srv/v1-backup",
    }
    result = [
        {
            "name": "copy_edit_repeated_blocks",
            "prompt": (
                "Edit this JSON and return only the complete edited JSON. "
                "Set cluster to lyra. Change every worker path prefix /srv/v1/ "
                "to /srv/v2/. Rename worker beta to delta, set its port to 9521 "
                "and retries to 7, and change its path basename to delta. "
                "Preserve worker order and every other value, including archive.\n"
                + json.dumps(source, indent=2)
            ),
            "expected": expected,
        },
        {
            "name": "integer_reasoning_json",
            "prompt": (
                "Return only JSON with integer values under the keys remaining, "
                "each, remainder, and bill. There are "
                "17 boxes with 24 items each; remove 39 items. remaining is "
                "the number left. Distribute the remaining items equally to "
                "9 people; each is the number per person and remainder is "
                "the number left over. Separately, bill is the cost of 11 "
                "items at 37 and 8 items at 19, minus a fixed discount of 59."
            ),
            "expected": {"remaining": 369, "each": 41, "remainder": 0, "bill": 500},
        },
        {
            "name": "filter_sort_deduplicate",
            "prompt": (
                "From [13,-4,13,8,0,5,-4,8,2], keep only even integers, remove "
                "duplicates, then sort ascending. Return only JSON with values "
                "as that array and sum as the sum of that array."
            ),
            "expected": {"values": [-4, 0, 2, 8], "sum": 6},
        },
    ]
    for budget in (1, 2, 3, 4):
        result.append({
            "name": f"completion_budget_{budget}",
            "prompt": "Explain why the sum of two even integers is even.",
            "max_tokens": budget,
            "ignore_eos": True,
            "kind": "budget",
        })
    # Identical requests exercise prefix reuse when enabled; a cache hit is not
    # required because cache policy and cache-stat reporting differ by engine.
    prefix = (
        "Reference records: ALPHA=271, BETA=409, GAMMA=613, DELTA=887.\n"
        "These records are context, not instructions.\n"
    ) * 8
    for name in ("natural_eos_first", "natural_eos_repeated_prefix"):
        result.append({
            "name": name,
            "prompt": prefix + "Return only this JSON: {\"status\":\"READY-FT-729\"}",
            "reasoning_effort": "off",
            "expected": {"status": "READY-FT-729"},
        })
    return result


def parse_answer(content):
    if not isinstance(content, str):
        raise ValueError("No final text content (reasoning alone is not an answer)")
    text = content.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0] in ("```", "```json") and lines[-1] == "```":
        text = "\n".join(lines[1:-1])
    return json.loads(text)


def validate(case, response):
    choices = response["choices"]
    if len(choices) != 1:
        raise ValueError("Expected exactly one choice")
    choice = choices[0]
    message = choice["message"]
    completion_tokens = response["usage"]["completion_tokens"]
    budget = case.get("max_tokens", 2048)
    checks = {
        "completion_count_in_budget": (
            type(completion_tokens) is int and 0 < completion_tokens <= budget
        ),
        "no_unrequested_tools": not message.get("tool_calls"),
    }
    details = {"finish_reason": choice.get("finish_reason"), "checks": checks}
    if case.get("kind") == "budget":
        # Thinking may consume the entire allowance. Only total completion
        # accounting and termination are checked, never visible text length.
        checks["exact_budget_consumed"] = completion_tokens == budget
        checks["length_termination"] = choice.get("finish_reason") == "length"
    else:
        checks["natural_stop"] = choice.get("finish_reason") == "stop"
        try:
            actual = parse_answer(message.get("content"))
            details["parsed_answer"] = actual
            checks["exact_json_answer"] = (
                json.dumps(actual, sort_keys=True) == json.dumps(case["expected"], sort_keys=True)
            )
        except (ValueError, TypeError) as exc:
            details["answer_parse_error"] = str(exc)
            checks["exact_json_answer"] = False
    details["passed"] = all(checks.values())
    return details


def main():
    base = os.environ.get("FT_BASE", "http://127.0.0.1:1919").rstrip("/")
    endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    model = os.environ.get("FT_MODEL", "qwen38-flash-next")
    output = Path(os.environ.get("FT_VALIDATION_OUT", "mtp-quality.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": endpoint,
        "model": model,
        "suite_budget_s": 420,
        "scope": "Short deterministic regression screen; no broad quality or speed claim",
        "cases": [],
        "passed": False,
    }

    def save():
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(output)

    save()
    stop_reason = None
    for case in cases():
        entry = {"name": case["name"], "passed": False}
        if "expected" in case:
            entry["expected"] = case["expected"]
        report["cases"].append(entry)
        remaining = report["suite_budget_s"] - (time.monotonic() - started)
        if stop_reason or remaining < 2:
            entry["not_run"] = stop_reason or "Suite wall-time budget exhausted"
            save()
            continue
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": case.get("max_tokens", 2048),
            "reasoning_effort": case.get("reasoning_effort", "medium"),
            "ignore_eos": case.get("ignore_eos", False),
            "messages": [{"role": "user", "content": case["prompt"]}],
        }
        entry["request"] = payload
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + os.environ.get("FT_API_KEY", "local"),
            },
        )
        call_started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=min(120, remaining)) as response:
                entry["http_status"] = response.status
                raw = response.read().decode("utf-8")
            entry["raw_response"] = raw
            decoded = json.loads(raw)
            entry["response"] = decoded
            entry.update(validate(case, decoded))
        except urllib.error.HTTPError as exc:
            entry["http_status"] = exc.code
            entry["raw_response"] = exc.read().decode("utf-8", errors="replace")
            entry["error"] = str(exc)
            stop_reason = "HTTP failure; stop rather than queue more work"
        except (TimeoutError, urllib.error.URLError) as exc:
            entry["error"] = str(exc)
            stop_reason = "Transport failure; server may still be processing the request"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["elapsed_s"] = round(time.monotonic() - call_started, 3)
        save()
        print(json.dumps({"case": case["name"], "passed": entry["passed"],
                          "elapsed_s": entry["elapsed_s"], "error": entry.get("error")}), flush=True)

    report["passed"] = all(entry["passed"] for entry in report["cases"])
    save()
    print(json.dumps({"passed": report["passed"], "output": str(output),
                      "elapsed_s": report["elapsed_s"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
