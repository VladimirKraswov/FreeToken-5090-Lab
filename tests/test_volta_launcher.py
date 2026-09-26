"""Check that the optional V100 launcher cannot displace the NInfer service."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


LAUNCHER = Path(__file__).resolve().parents[1] / "deploy/volta/serve-standalone.sh"


def _run(tmp_path: Path, *, ninfer_active: bool, free_kib: int) -> tuple[int, str, list[str]]:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("{}")
    bank = tmp_path / "bank"
    bank.mkdir()
    shims = tmp_path / "shims"
    shims.mkdir()
    capture = tmp_path / "args.txt"
    for name, code in {
        "systemctl": f"#!/bin/sh\nexit {0 if ninfer_active else 3}\n",
        "df": f"#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\n'\nprintf 'test 100000000 0 {free_kib} 0%% /\\n'\n",
        "ft": '#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n',
    }.items():
        path = shims / name
        path.write_text(code)
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{shims}:{os.environ['PATH']}",
        "MODEL_DIR": str(checkpoint),
        "FT_V100_BANK_DIR": str(bank),
        "FT_BIN": str(shims / "ft"),
        "FT_CONTEXT_TOKENS": "65536",
        "CAPTURE": str(capture),
    }
    result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True)
    return result.returncode, result.stderr, capture.read_text().splitlines() if capture.exists() else []


def test_v100_launcher_refuses_an_active_ninfer_service(tmp_path: Path) -> None:
    code, error, args = _run(tmp_path, ninfer_active=True, free_kib=80 * 1024 * 1024)
    assert code == 2 and "Stop ninfer-v100.service" in error
    assert not args


def test_v100_launcher_refuses_undersized_bank_storage(tmp_path: Path) -> None:
    code, error, args = _run(tmp_path, ninfer_active=False, free_kib=20 * 1024 * 1024)
    assert code == 2 and "70 GiB free" in error
    assert not args


def test_v100_launcher_selects_triton_and_disk_ple(tmp_path: Path) -> None:
    code, error, args = _run(tmp_path, ninfer_active=False, free_kib=80 * 1024 * 1024)
    assert code == 0, error
    assert args[args.index("--quant-backend") + 1] == "moe.nvfp4=triton"
    assert args[args.index("--ple-backend") + 1] == "disk"
    assert args[args.index("--max-seq-len-override") + 1] == "65536"
