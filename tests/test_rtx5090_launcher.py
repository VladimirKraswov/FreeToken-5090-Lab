"""Exercise the deployment launcher without importing Torch or starting a server."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


LAUNCHER = Path(__file__).resolve().parents[1] / "deploy/rtx5090/serve.sh"
WRAPPER = LAUNCHER.with_name("serve-vm5200.sh")


def _launch(
    tmp_path: Path, *, launcher: Path = LAUNCHER, **overrides: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    capture = tmp_path / "args.txt"
    fake_ft = tmp_path / "ft"
    fake_ft.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
    fake_ft.chmod(0o755)
    env = {
        **os.environ,
        "FT_BIN": str(fake_ft),
        "MODEL_DIR": str(tmp_path / "checkpoint"),
        "CAPTURE": str(capture),
        "FT_REPO_ROOT": str(LAUNCHER.parents[2]),
    }
    for name in ("FT_CONTEXT_TOKENS", "FT_KV_RESERVE_TOKENS"):
        env.pop(name, None)
    env.update(overrides)
    result = subprocess.run(["bash", str(launcher)], env=env, capture_output=True, text=True)
    return result, capture.read_text().splitlines() if capture.exists() else []


def _value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_default_context_and_kv_reserve_match(tmp_path: Path) -> None:
    result, args = _launch(tmp_path)
    assert result.returncode == 0, result.stderr
    assert _value(args, "--max-seq-len-override") == "262144"
    assert _value(args, "--kv-reserve-tokens") == "262144"


def test_context_can_change_without_rebuilding(tmp_path: Path) -> None:
    result, args = _launch(tmp_path, FT_CONTEXT_TOKENS="163840", FT_KV_RESERVE_TOKENS="180224")
    assert result.returncode == 0, result.stderr
    assert _value(args, "--max-seq-len-override") == "163840"
    assert _value(args, "--kv-reserve-tokens") == "180224"


def test_context_rejects_undersized_reserve(tmp_path: Path) -> None:
    result, args = _launch(tmp_path, FT_CONTEXT_TOKENS="196608", FT_KV_RESERVE_TOKENS="131072")
    assert result.returncode == 2
    assert "KV reserve must cover context" in result.stderr
    assert not args


def test_vm_wrapper_uses_the_same_context(tmp_path: Path) -> None:
    result, args = _launch(tmp_path, launcher=WRAPPER)
    assert result.returncode == 0, result.stderr
    assert _value(args, "--max-seq-len-override") == "262144"
    assert _value(args, "--kv-reserve-tokens") == "262144"
