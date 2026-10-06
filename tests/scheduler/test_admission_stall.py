"""A head of the prefill queue that keeps being refused is reported, with the reason the
admission check had (upstream #453: the engine sat at active=1, 0 tok/s and logged nothing).
CPU, real CacheManager/TableManager; no engine."""

from __future__ import annotations

import time

import pytest
import torch

from freetoken.core import SamplingParams


class _Log:
    def __init__(self):
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg, *a, **k):
        self.warnings.append(msg)

    def info(self, msg, *a, **k):
        self.infos.append(msg)


def _setup_context() -> None:
    from freetoken.core import Context, get_global_ctx, set_global_ctx

    try:
        get_global_ctx()
    except AssertionError:
        set_global_ctx(Context(page_size=1))


def _managers(monkeypatch, *, num_pages=64, page_size=16, max_running=2, type="radix", pool=None):
    from freetoken.scheduler import prefill
    from freetoken.scheduler.cache import CacheManager
    from freetoken.scheduler.decode import DecodeManager
    from freetoken.scheduler.table import TableManager

    _setup_context()
    log = _Log()
    monkeypatch.setattr(prefill, "logger", log)
    pt = torch.zeros(max_running + 1, 1024, dtype=torch.int32)
    cm = CacheManager(num_pages, page_size, pt, type, linear_state_pool=pool)
    tm = TableManager(max_running_reqs=max_running, page_table=pt)
    # a threshold of one millisecond; the repeat interval is still floored at 60 s
    pm = prefill.PrefillManager(cm, tm, DecodeManager(page_size), stall=prefill.AdmissionStall(0.001))
    return cm, tm, pm, log


def _pending(uid, prompt_len, max_tokens):
    from freetoken.scheduler.utils import PendingReq

    return PendingReq(uid, torch.arange(prompt_len, dtype=torch.int32), SamplingParams(max_tokens=max_tokens))


def test_stall_clock_warns_after_threshold_then_every_interval():
    from freetoken.scheduler.prefill import AdmissionStall

    s = AdmissionStall(30.0)
    assert not s.refused(1, 100.0)  # first refusal starts the clock
    assert not s.refused(1, 129.0)
    assert s.refused(1, 130.0)
    assert not s.refused(1, 131.0)
    assert not s.refused(1, 189.0)
    assert s.refused(1, 190.0)  # repeats every 60 s
    assert s.warnings == 2 and s.since == 100.0
    assert not s.refused(2, 191.0)  # a different head restarts the clock
    assert s.uid == 2 and s.warnings == 0 and not s.refused(2, 220.0) and s.refused(2, 221.0)


def test_stall_clock_waits_out_running_progress():
    from freetoken.scheduler.prefill import AdmissionStall

    s = AdmissionStall(30.0)
    assert not s.refused(1, 0.0, progress=100)
    # (a) ten minutes behind a request whose length keeps growing: FIFO, never a warning
    assert not any(s.refused(1, float(t), progress=100 + t) for t in range(1, 601))
    # (b) it stops advancing: warn warn_after later, then on the repeat interval
    assert not s.refused(1, 629.0, progress=700)
    assert s.refused(1, 630.0, progress=700)
    assert s.since == 0.0 and s.progress_at == 600.0  # total wait kept, stall measured apart
    assert not s.refused(1, 689.0, progress=700) and s.refused(1, 690.0, progress=700)
    # it moves again: quiet until it has stood still for a full warn_after
    assert not s.refused(1, 700.0, progress=701) and not s.refused(1, 729.0, progress=701)
    assert s.refused(1, 730.0, progress=701)
    # (c) nothing running (None): the plain clock, repeating from the last warning
    assert not s.refused(1, 789.0) and s.refused(1, 790.0)
    s = AdmissionStall(30.0)
    assert not s.refused(2, 0.0) and not s.refused(2, 29.0) and s.refused(2, 30.0)


def test_stall_clock_off_at_zero():
    from freetoken.scheduler.prefill import AdmissionStall

    s = AdmissionStall(0.0)
    assert not any(s.refused(1, t) for t in (0.0, 1e3, 1e6))


def test_impossible_request_is_rejected_and_next_request_is_admitted(monkeypatch):
    cm, tm, pm, log = _managers(monkeypatch)  # 64 pages x 16 = 1024 KV tokens
    pm.pending_list = [_pending(7, 100, 2000), _pending(8, 10, 4)]
    batch = pm.schedule_next_batch(512)
    assert [req.uid for req in batch.reqs] == [8]
    assert pm.pending_list == [] and tm.available_size == 1
    errors = pm.pop_rejected_requests()
    assert len(errors) == 1 and errors[0].uid == 7
    assert errors[0].code == "context_length_exceeded"
    assert errors[0].error.startswith("prompt is too long: 2112 tokens > 1024 maximum")
    assert "prompt 100 + max_tokens 2000" in errors[0].error
    assert "page-rounded KV budget" in errors[0].error
    assert pm.pop_rejected_requests() == []
    assert pm.schedule_next_batch(512) is None
    assert len(log.warnings) == 1


def test_all_impossible_requests_leave_no_stalled_head_or_allocations(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    pm.pending_list = [_pending(7, 1000, 25), _pending(8, 16, 1024)]
    pm.stall.refused(7, 0.0)
    assert pm.schedule_next_batch(512) is None
    assert [error.uid for error in pm.pop_rejected_requests()] == [7, 8]
    assert not pm.runnable and pm.stall.uid is None
    assert tm.available_size == 2 and len(cm.free_slots) == cm.num_pages
    cm.check_integrity()


def test_temporary_kv_pressure_keeps_fifo_and_does_not_reject(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    held_pages = cm._allocate(60)
    pm.pending_list = [_pending(7, 100, 16), _pending(8, 10, 4)]
    assert pm.schedule_next_batch(512) is None  # request 8 would fit, but cannot pass 7
    assert [req.uid for req in pm.pending_list] == [7, 8]
    assert pm.pop_rejected_requests() == [] and tm.available_size == 2
    cm._free(cm._page_to_token(held_pages))
    batch = pm.schedule_next_batch(512)
    assert [req.uid for req in batch.reqs] == [7, 8]


def test_running_output_reservations_are_temporary_pressure(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    running = _Running(20)
    running.remain_len = 1000
    pm.decode_manager.running_reqs = {running}
    pm.pending_list = [_pending(7, 100, 16)]
    assert pm.schedule_next_batch(512) is None
    assert pm.pop_rejected_requests() == [] and [req.uid for req in pm.pending_list] == [7]
    pm.decode_manager.running_reqs.clear()
    assert pm.schedule_next_batch(512).reqs[0].uid == 7


def _cache_prefix(cm, length):
    pages = cm._allocate(length // cm.page_size)
    cm.prefix_cache.insert_prefix(torch.arange(length, dtype=torch.int32), cm._page_to_token(pages))


def test_shared_prefix_does_not_make_an_impossible_sequence_fit(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    _cache_prefix(cm, 800)
    pm.pending_list = [_pending(7, 1000, 25)]
    before = cm.prefix_cache.size_info
    assert pm.schedule_next_batch(1024) is None
    assert pm.pop_rejected_requests()[0].uid == 7
    assert cm.prefix_cache.size_info == before  # no match, lock or eviction on rejection
    assert tm.available_size == 2
    cm.check_integrity()


def test_exact_capacity_request_with_shared_prefix_is_admitted(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    _cache_prefix(cm, 800)
    pm.pending_list = [_pending(7, 1000, 24)]
    batch = pm.schedule_next_batch(1024)
    assert batch.reqs[0].cache_handle.cached_len == 800
    assert pm.pop_rejected_requests() == []


def test_two_requests_sharing_prefix_do_not_double_charge_it(monkeypatch):
    cm, tm, pm, _ = _managers(monkeypatch)
    _cache_prefix(cm, 800)
    pm.pending_list = [_pending(7, 816, 16), _pending(8, 816, 16)]
    batch = pm.schedule_next_batch(512)
    assert [req.uid for req in batch.reqs] == [7, 8]
    assert [req.cache_handle.cached_len for req in batch.reqs] == [800, 800]
    assert pm.pop_rejected_requests() == []


def test_rejection_after_chunk_does_not_drop_its_continuation(monkeypatch):
    from freetoken.scheduler.prefill import ChunkedReq

    cm, tm, pm, _ = _managers(monkeypatch)
    pm.pending_list = [_pending(7, 40, 4), _pending(8, 100, 2000), _pending(9, 10, 4)]
    batch = pm.schedule_next_batch(16)
    assert len(batch.reqs) == 1 and isinstance(batch.reqs[0], ChunkedReq)
    assert [req.uid for req in pm.pending_list] == [7, 9]
    assert pm.pending_list[0].chunked_req is batch.reqs[0]
    assert [error.uid for error in pm.pop_rejected_requests()] == [8]


@pytest.mark.parametrize("cache_type,swa_paged", [("radix", True), ("swa_radix", False), ("owned", False)])
def test_tiered_or_unknown_pool_keeps_existing_admission_policy(monkeypatch, cache_type, swa_paged):
    cm, tm, pm, _ = _managers(monkeypatch)
    cm.cache_type, cm.swa_paged = cache_type, swa_paged
    pm.pending_list = [_pending(7, 100, 2000)]
    assert pm.schedule_next_batch(512) is None
    assert pm.pop_rejected_requests() == [] and [req.uid for req in pm.pending_list] == [7]


def test_offline_rejection_drains_valid_batch_and_next_generate_reuses_resources(monkeypatch):
    from types import SimpleNamespace

    from freetoken.llm import LLM
    from freetoken.message import DetokenizeMsg

    cm, tm, pm, _ = _managers(monkeypatch, num_pages=4)
    llm = LLM.__new__(LLM)
    llm.prefill_manager = pm
    llm.prefill_budget = 512
    llm.engine = SimpleNamespace(prefill_chunk_now=lambda budget: budget)
    llm.tokenizer = SimpleNamespace(decode=lambda ids: " ".join(map(str, ids)))
    llm.eos_token_ids = set()
    llm.send_result = llm.offline_send_result
    finished = []

    def run_without_model():
        while True:
            for msg in llm.offline_receive_msg(blocking=not pm.runnable):
                # Exercise the final admission guard independently of the front-door clamp.
                pm.add_one_req(msg)
            batch = llm._schedule_prefill_batch()
            if batch is None:
                continue
            cm.allocate_paged(batch.reqs)
            for req in batch.reqs:
                req.complete_one()
                req.append_host(torch.tensor([77], dtype=torch.int32))
                cm.cache_req(req, finished=True)
                tm.free(req.table_idx)
                llm.offline_send_result([DetokenizeMsg(uid=req.uid, next_token=77, finished=True)])
                finished.append(req.uid)

    llm.run_forever = run_without_model
    with pytest.raises(ValueError, match="request 0: prompt is too long: 96 tokens > 64"):
        llm.generate([list(range(80)), list(range(16))], SamplingParams(max_tokens=1))
    assert finished == [1] and llm.status_map[1].output_ids == [77]
    assert not pm.runnable and tm.available_size == 2
    cm.check_integrity()

    assert llm.generate([list(range(16))], SamplingParams(max_tokens=1)) == [
        {"text": "77", "token_ids": [77]}
    ]
    assert finished == [1, 0] and tm.available_size == 2
    cm.check_integrity()


def test_no_request_slot_then_admitted_logs_the_wait(monkeypatch):
    cm, tm, pm, log = _managers(monkeypatch, max_running=1)
    held = tm.allocate()
    pm.pending_list = [_pending(3, 20, 4)]
    assert pm.schedule_next_batch(512) is None
    time.sleep(0.01)
    assert pm.schedule_next_batch(512) is None
    assert len(log.warnings) == 1
    assert "no free request slot (all 1 of --max-running-requests are taken)" in log.warnings[0]
    assert "Nothing is running that could free it" in log.warnings[0]

    tm.free(held)
    batch = pm.schedule_next_batch(512)
    assert batch is not None and batch.reqs[0].uid == 3
    assert len(log.infos) == 1 and "request 3 admitted after" in log.infos[0]
    assert pm.stall.uid is None


def test_brief_refusal_says_nothing(monkeypatch):
    cm, tm, pm, log = _managers(monkeypatch, max_running=1)
    pm.stall = type(pm.stall)(30.0)
    held = tm.allocate()
    pm.pending_list = [_pending(3, 20, 4)]
    assert pm.schedule_next_batch(512) is None
    tm.free(held)
    assert pm.schedule_next_batch(512) is not None
    assert not log.warnings and not log.infos and pm.stall.uid is None


def test_gdn_slot_refusal_names_the_slot_count(monkeypatch):
    from freetoken.kvcache.linear_state_pool import LinearStatePool
    from freetoken.models.config import LinearGatedDeltaGroupConfig

    g = LinearGatedDeltaGroupConfig(
        name="linear", layer_ids=(0,), num_key_heads=2, num_value_heads=4,
        key_head_dim=16, value_head_dim=16, conv_kernel_dim=4, output_gate="silu",
    )
    pool = LinearStatePool(group=g, num_slots=5, dtype=torch.bfloat16,
                           device=torch.device("cpu"), tp_size=1)
    cm, tm, pm, log = _managers(monkeypatch, type="hybrid_radix", pool=pool)
    pool.alloc(3)  # 4 usable slots, 1 left; nothing in the tree to evict
    pm.pending_list = [_pending(5, 40, 4)]
    assert pm.schedule_next_batch(512) is None
    time.sleep(0.01)
    assert pm.schedule_next_batch(512) is None
    assert len(log.warnings) == 1
    assert "needs 3 GDN state slots and 1 were free" in log.warnings[0]
    assert "pool of 4" in log.warnings[0]


def test_running_requests_change_the_outlook(monkeypatch):
    from freetoken.scheduler.prefill import describe_refusal

    cm, tm, pm, _ = _managers(monkeypatch)
    pm.decode_manager.running_reqs = {object(), object()}
    msg = describe_refusal(("kv", 64, 32, 16), _pending(1, 10, 4), 450.0, 0, cm, tm, pm.decode_manager,
                           no_progress_for=45.0)
    assert "refused admission for 450s" in msg
    assert "queued behind 2 running request(s) that have made no progress for 45s" in msg
    assert "can never" not in msg
    assert "no reason was recorded" in describe_refusal(
        None, _pending(1, 10, 4), 45.0, 0, cm, tm, pm.decode_manager
    )


class _Running:
    """A decoding request as the admission path sees it: a length and an output budget."""

    def __init__(self, device_len):
        self.device_len = device_len
        self.remain_len = 100


class _FakeTime:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


def test_side_request_behind_a_generation_warns_only_when_it_stops(monkeypatch):
    """--max-running-requests 1 with Open WebUI: the title request waits out a long generation
    (no warning), and is reported only once that generation stops being stepped."""
    from freetoken.scheduler import prefill

    cm, tm, pm, log = _managers(monkeypatch, max_running=1)
    clock = _FakeTime()
    monkeypatch.setattr(prefill, "time", clock)
    pm.stall = prefill.AdmissionStall(30.0)
    tm.allocate()  # the generation's slot
    gen = _Running(500)
    pm.decode_manager.running_reqs = {gen}
    pm.pending_list = [_pending(9, 20, 4)]
    for step in range(600 * 20):  # 10 minutes of 50 ms decode steps
        clock.t = step * 0.05
        gen.device_len += 1
        assert pm.schedule_next_batch(512) is None
    assert not log.warnings
    stopped = clock.t
    clock.t = stopped + 29.0
    assert pm.schedule_next_batch(512) is None
    assert not log.warnings
    clock.t = stopped + 30.0
    assert pm.schedule_next_batch(512) is None
    assert len(log.warnings) == 1
    msg = log.warnings[0]
    assert "no free request slot" in msg
    assert "refused admission for 630s" in msg
    assert "queued behind 1 running request(s) that have made no progress for 30s" in msg
