"""Record a short, repeatable completion from one standalone server."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def run(url: str, model: str, output: Path) -> None:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Вычисли 17 * 19 и ответь только числом."}],
        "temperature": 0,
        "seed": 1234,
        "max_tokens": 96,
    }
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    wall_seconds = time.perf_counter() - started
    record = {"request": body, "response": result, "wall_seconds": wall_seconds}
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    choice = result["choices"][0]
    print(json.dumps({
        "content": choice["message"].get("content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "wall_seconds": round(wall_seconds, 3),
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.model, args.out)
