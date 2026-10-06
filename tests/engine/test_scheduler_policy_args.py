"""Fair scheduling stays opt-in and rejects unsynchronized rank-local policies."""

import json

import pytest

pytest.importorskip("torch")

from freetoken.server.args import parse_args


def _parse(tmp_path, *args):
    (tmp_path / "config.json").write_text(json.dumps({
        "architectures": ["Qwen4ExpForConditionalGeneration"],
        "model_type": "qwen4_exp", "torch_dtype": "bfloat16",
    }))
    parsed, _ = parse_args([
        "--model", str(tmp_path), "--dtype", "bfloat16",
        "--tool-call-parser", "llama3", "--reasoning-parser", "off", *args,
    ], False)
    return parsed


def test_defaults_preserve_prefill_priority(tmp_path):
    assert _parse(tmp_path).scheduler_policy == "prefill-first"


def test_fair_policy_budgets_reach_config(tmp_path):
    args = _parse(tmp_path, "--scheduler-policy", "fair",
                  "--scheduler-decode-burst-ms", "1500", "--scheduler-decode-burst-steps", "32")
    assert args.scheduler_policy == "fair"
    assert args.scheduler_decode_burst_ms == 1500
    assert args.scheduler_decode_burst_steps == 32


@pytest.mark.parametrize("flag,value", [
    ("--scheduler-decode-burst-ms", "0"), ("--scheduler-decode-burst-ms", "nan"),
    ("--scheduler-decode-burst-ms", "inf"), ("--scheduler-decode-burst-steps", "0"),
    ("--tp-size", "2"), ("--pp-size", "2"),
])
def test_invalid_budgets_and_multiple_ranks_fail_at_parse(tmp_path, flag, value):
    with pytest.raises(SystemExit):
        _parse(tmp_path, "--scheduler-policy", "fair", flag, value)
