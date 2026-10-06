"""Service bounds need neither CUDA nor a model checkpoint."""

import importlib.util
from pathlib import Path

import pytest


_path = Path(__file__).resolve().parents[2] / "python/freetoken/scheduler/policy.py"
_spec = importlib.util.spec_from_file_location("fair_policy_under_test", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
FairBatchPolicy = _module.FairBatchPolicy


def _next(policy, prefill=True, generation=True):
    return policy.prefer_generation(prefill_pending=prefill, generation_runnable=generation)


def test_both_queues_progress_under_sustained_contention():
    policy = FairBatchPolicy(1000, 3)
    selected = []
    for _ in range(24):
        generation = _next(policy)
        selected.append(generation)
        policy.completed(generation=generation, elapsed_seconds=0.01)
    assert selected == [False, True, True, True] * 6


def test_completed_service_time_caps_the_generation_burst():
    policy = FairBatchPolicy(200, 32)
    policy.completed(generation=False, elapsed_seconds=12.0)
    for _ in range(3):
        assert _next(policy)
        policy.completed(generation=True, elapsed_seconds=0.06)
    assert _next(policy)
    policy.completed(generation=True, elapsed_seconds=0.06)
    assert not _next(policy)


def test_one_slow_generation_batch_still_runs_before_returning_to_prefill():
    policy = FairBatchPolicy(1, 32)
    policy.completed(generation=False, elapsed_seconds=5.0)
    assert _next(policy)
    policy.completed(generation=True, elapsed_seconds=3.0)
    assert not _next(policy)


@pytest.mark.parametrize("prefill,generation,expected", [(False, True, True), (True, False, False), (False, False, False)])
def test_no_contention_resets_old_bursts(prefill, generation, expected):
    policy = FairBatchPolicy(1000, 8)
    policy.completed(generation=False, elapsed_seconds=0.1)
    assert _next(policy, prefill, generation) is expected
    assert not _next(policy)


def test_uncontended_final_prefill_yields_to_its_first_generation():
    policy = FairBatchPolicy(1000, 8)
    assert not _next(policy, prefill=True, generation=False)
    policy.completed(generation=False, elapsed_seconds=5.0)
    assert _next(policy, prefill=True, generation=True)


def test_a_refused_prefill_keeps_getting_a_turn_after_generation_fallback():
    policy = FairBatchPolicy(1000, 8)
    for _ in range(12):
        assert not _next(policy)
        policy.completed(generation=True, elapsed_seconds=0.01)


@pytest.mark.parametrize("ms,steps", [(0, 8), (-1, 8), (float("nan"), 8), (float("inf"), 8), (200, 0), (200, -1)])
def test_invalid_budgets_are_rejected(ms, steps):
    with pytest.raises(ValueError):
        FairBatchPolicy(ms, steps)
