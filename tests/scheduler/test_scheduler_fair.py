"""Exercise policy selection and the drain boundary with CPU scheduler doubles."""

from types import SimpleNamespace

import pytest

pytest.importorskip("torch")

from freetoken.scheduler import scheduler as sched_mod
from freetoken.scheduler.policy import FairBatchPolicy
from freetoken.scheduler.scheduler import Scheduler


def _batch(prefill, verify=False):
    return SimpleNamespace(is_prefill=prefill, spec_verify=verify, prompt_admissions=[])


def _scheduler(policy=True):
    scheduler = Scheduler.__new__(Scheduler)
    calls = []
    scheduler._fair_policy = FairBatchPolicy(200, 2) if policy else None
    scheduler.prefill_budget = 4096
    scheduler.spec_k = 0
    scheduler.engine = SimpleNamespace(prefill_chunk_now=lambda budget: budget)
    scheduler.prefill_manager = SimpleNamespace(
        runnable=True, pending_list=[object()],
        schedule_next_batch=lambda budget: (calls.append("prefill"), _batch(True))[1],
    )
    scheduler.decode_manager = SimpleNamespace(
        runnable=True,
        schedule_next_batch=lambda: (calls.append("decode"), _batch(False))[1],
    )
    scheduler._prepare_batch = lambda batch: SimpleNamespace(batch=batch)
    scheduler._report_prompt_admissions = lambda batch: None
    return scheduler, calls


def test_disabled_policy_keeps_prefill_priority():
    scheduler, calls = _scheduler(policy=False)
    for _ in range(3):
        assert scheduler._schedule_next_batch().batch.is_prefill
    assert calls == ["prefill"] * 3


def test_generation_turn_does_not_mutate_pending_prefill():
    scheduler, calls = _scheduler()
    for _ in range(4):
        batch = scheduler._schedule_next_batch().batch
        scheduler._fair_policy.completed(generation=not batch.is_prefill, elapsed_seconds=0.01)
    assert calls == ["prefill", "decode", "decode", "prefill"]


def test_refused_prefill_falls_back_to_generation():
    scheduler, calls = _scheduler()
    scheduler.prefill_manager.schedule_next_batch = lambda budget: calls.append("refused")
    assert not scheduler._schedule_next_batch().batch.is_prefill
    assert calls == ["refused", "decode"]


def test_generation_turn_prefers_existing_mtp_verify():
    scheduler, calls = _scheduler()
    scheduler.spec_k = 3
    scheduler._schedule_spec_batch = lambda: (calls.append("verify"), _batch(True, True))[1]
    scheduler._fair_policy.completed(generation=False, elapsed_seconds=2.0)
    assert scheduler._schedule_next_batch().batch.spec_verify
    assert calls == ["verify"]


def test_generation_turn_without_drafts_uses_regular_decode():
    scheduler, calls = _scheduler()
    scheduler.spec_k = 3
    scheduler._schedule_spec_batch = lambda: None
    scheduler._fair_policy.completed(generation=False, elapsed_seconds=2.0)
    assert not scheduler._schedule_next_batch().batch.is_prefill
    assert calls == ["decode"]


def test_rejected_admission_replies_are_drained_even_without_a_batch():
    scheduler, calls = _scheduler()
    rejected = [object()]
    replies = []
    scheduler.send_result = replies.extend
    scheduler.prefill_manager.pop_rejected_requests = lambda: rejected.copy()
    scheduler.prefill_manager.schedule_next_batch = lambda budget: None
    assert not scheduler._schedule_next_batch().batch.is_prefill
    assert replies == rejected


def test_mtp_service_is_charged_after_the_normal_loop_drains(monkeypatch):
    scheduler, calls = _scheduler()
    scheduler.spec_k = 3
    scheduler._schedule_spec_batch = lambda: (calls.append("verify"), _batch(True, True))[1]
    scheduler._fair_policy.completed(generation=False, elapsed_seconds=2.0)
    scheduler._pending_rebuild = None
    scheduler.receive_msg = lambda blocking: []
    scheduler._restore_linear_states = lambda batch: calls.append("restore")
    scheduler._forward = lambda forward_input: calls.append("forward")
    scheduler._process_last_data = lambda data: calls.append("drained")
    scheduler._flush_abort_acks = lambda: calls.append("abort-acks")
    times = iter([10.0, 10.25])

    def clock():
        calls.append("clock")
        return next(times)

    monkeypatch.setattr(sched_mod.time, "monotonic", clock)
    scheduler.normal_loop()
    assert calls == ["clock", "verify", "restore", "forward", "drained", "clock", "abort-acks"]
    assert not scheduler._fair_policy.prefer_generation(prefill_pending=True, generation_runnable=True)


def _hybrid_scheduler(page_size):
    import torch
    from freetoken.kvcache.linear_state_pool import LinearStatePool
    from freetoken.models.config import LinearGatedDeltaGroupConfig
    from freetoken.scheduler.cache import CacheManager
    from freetoken.scheduler.decode import DecodeManager
    from freetoken.scheduler.prefill import PrefillManager
    from freetoken.scheduler.table import TableManager

    group = LinearGatedDeltaGroupConfig(
        name="linear", layer_ids=(0,), num_key_heads=2, num_value_heads=4,
        key_head_dim=16, value_head_dim=16, conv_kernel_dim=4, output_gate="silu",
    )
    pool = LinearStatePool(group=group, num_slots=16, dtype=torch.bfloat16,
                           device=torch.device("cpu"), tp_size=1)
    page_table = torch.zeros((4, 1024), dtype=torch.int32)
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.cache_manager = CacheManager(640 // page_size + 2, page_size, page_table,
                                           "hybrid_radix", linear_state_pool=pool)
    scheduler.table_manager = TableManager(3, page_table)
    scheduler.token_pool = scheduler.table_manager.token_pool
    scheduler.decode_manager = DecodeManager(page_size)
    scheduler.prefill_manager = PrefillManager(scheduler.cache_manager, scheduler.table_manager,
                                               scheduler.decode_manager)
    scheduler._fair_policy = FairBatchPolicy(1000, 3)
    scheduler.prefill_budget = 64
    scheduler.spec_k = 3
    scheduler.device = torch.device("cpu")
    scheduler.engine = SimpleNamespace(max_seq_len=1024, linear_state_pool=pool,
                                       prefill_chunk_now=lambda budget: budget)
    scheduler.config = SimpleNamespace(page_size=page_size)
    scheduler.finished_reqs = set()
    scheduler.eos_token_ids = set()
    scheduler.toolcall_anchor_id = None
    scheduler._pending_abort_acks = set()
    scheduler._last_data = None
    scheduler.status_reporter = SimpleNamespace(report_batch=lambda *args, **kwargs: None)
    scheduler._kv_usage_pages = scheduler.cache_manager.page_usage
    scheduler._mamba_slot_usage = lambda: None
    scheduler._swa_token_usage = lambda: None
    scheduler._gpu_mem_bytes = lambda: 0
    replies = []
    scheduler.send_result = replies.extend

    def prepare(batch):
        scheduler.cache_manager.allocate_paged(batch.reqs)
        scheduler._prepare_spec(batch)
        return SimpleNamespace(batch=batch)

    scheduler._prepare_batch = prepare
    return scheduler, pool, replies


def _complete_on_cpu(scheduler, forward_input, *, accepted=None):
    """Replace only model execution; use the real scheduler commit and page-release paths."""
    import torch
    from freetoken.engine.engine import ForwardOutput
    from freetoken.engine.spec import SpecResult

    batch = forward_input.batch
    scheduler._restore_linear_states(batch)
    pool = scheduler.engine.linear_state_pool
    for req in batch.reqs:
        if batch.spec_verify:
            assert accepted is not None
            state_len = req.spec_base_len - 1 + len(accepted)
        else:
            req.complete_one()
            state_len = req.cached_len
        for _, state in pool.state_views(req.linear_slot_idx):
            state.fill_(req.uid * 10 + state_len / 1024)
        if batch.is_prefill and not batch.spec_verify:
            frozen = req.mamba_ping_pong[req.mamba_next_track_idx]
            pool.copy_from(req.linear_slot_idx, frozen)
            req.mamba_next_track_idx = 1 - req.mamba_next_track_idx
            req.mamba_last_track_seqlen = req.cached_len
    scheduler.decode_manager.filter_reqs(batch.reqs)
    tokens = torch.tensor([900 + req.uid for req in batch.reqs], dtype=torch.int32)
    result = SpecResult(accepted if accepted is not None else tokens.tolist(), [])
    output = ForwardOutput(tokens, tokens, SimpleNamespace(synchronize=lambda: None), result)
    scheduler._process_last_data((forward_input, output))
    scheduler._fair_policy.completed(generation=not batch.is_prefill or batch.spec_verify,
                                      elapsed_seconds=0.01)


@pytest.mark.parametrize("page_size", [1, 64])
@pytest.mark.parametrize("resume_chunk", [False, True])
def test_paused_hybrid_chunk_survives_decode_mtp_abort_and_next_wave(page_size, resume_chunk):
    import torch
    from freetoken.core import SamplingParams
    from freetoken.message import AbortBackendMsg, ErrorReplyMsg
    from freetoken.scheduler.prefill import ChunkedReq
    from freetoken.scheduler.utils import PendingReq

    scheduler, pool, replies = _hybrid_scheduler(page_size)
    cm, tm, pm, dm = (scheduler.cache_manager, scheduler.table_manager,
                      scheduler.prefill_manager, scheduler.decode_manager)

    def pending(uid, length, output):
        return PendingReq(uid, torch.arange(uid * 1000, uid * 1000 + length, dtype=torch.int32),
                          SamplingParams(max_tokens=output, ignore_eos=True))

    def abort(uid):
        scheduler._process_one_msg(AbortBackendMsg(uid=uid))
        scheduler._flush_abort_acks()

    pm.pending_list.append(pending(1, 64, 256))
    _complete_on_cpu(scheduler, scheduler._schedule_next_batch())
    active = next(iter(dm.running_reqs))
    _complete_on_cpu(scheduler, scheduler._schedule_next_batch())

    long_prompt = pending(2, 192, 64)
    pm.pending_list.append(long_prompt)
    first_chunk = scheduler._schedule_next_batch()
    paused = first_chunk.batch.reqs[0]
    assert isinstance(paused, ChunkedReq)
    _complete_on_cpu(scheduler, first_chunk)
    assert long_prompt.chunked_req is paused and paused not in dm.running_reqs
    assert paused.cache_handle.cached_len == 64
    assert paused.chunk_upto == 64

    handle = paused.cache_handle
    slots = (paused.linear_slot_idx, *paused.mamba_ping_pong)
    snapshot_slot = handle.node.mamba_value
    protected_slots = (*slots, snapshot_slot)
    states = {(slot, name): state.clone() for slot in protected_slots
              for name, state in pool.state_views(slot)}
    pages = cm.page_table[paused.table_idx, :64].clone()

    def check_paused():
        assert long_prompt.chunked_req is paused and paused.cache_handle is handle
        assert (paused.linear_slot_idx, *paused.mamba_ping_pong) == slots
        assert torch.equal(cm.page_table[paused.table_idx, :64], pages)
        assert not set(pages[::page_size].tolist()).intersection(cm.free_slots.tolist())
        assert not set(protected_slots).intersection(pool._free_slots)
        assert handle.node.mamba_ref_count > 0
        for slot in protected_slots:
            for name, state in pool.state_views(slot):
                assert torch.equal(state, states[slot, name])

    # C fits alone but not alongside the promised outputs of A and the full prompt/output of B.
    pm.pending_list.append(pending(3, 64, 64))
    for verify in (False, True, False):
        if verify:
            active.spec_drafts = [71, 72, 73]
        step = scheduler._schedule_next_batch()
        assert step.batch.reqs == [active]
        assert step.batch.spec_verify is verify
        old_len = active.device_len if not verify else active.spec_base_len
        _complete_on_cpu(scheduler, step, accepted=[71, 77] if verify else None)
        assert active.device_len == old_len + (2 if verify else 1)
        assert active.spec_base_len is None and active.spec_alloc_len is None
        assert active.cached_len == active.device_len - 1
        check_paused()

    if resume_chunk:
        scheduler.prefill_budget = 192
        resumed = scheduler._schedule_next_batch()
        assert len(resumed.batch.reqs) == 1 and resumed.batch.reqs[0].uid == 2
        resumed_req = resumed.batch.reqs[0]
        assert not isinstance(resumed_req, ChunkedReq)
        assert resumed_req.cache_handle is handle and resumed_req.table_idx == paused.table_idx
        assert (resumed_req.linear_slot_idx, *resumed_req.mamba_ping_pong) == slots
        assert torch.equal(cm.page_table[resumed_req.table_idx, :64], pages)
        assert [req.uid for req in pm.pending_list] == [3]
        assert pm.pending_list[0].chunked_req is None and tm.available_size == 1
        _complete_on_cpu(scheduler, resumed)

    abort(2)
    assert [req.uid for req in pm.pending_list] == [3]
    assert all(req.uid != 2 for req in dm.running_reqs)
    counts = (tm.available_size, pool.num_free_slots, len(cm.free_slots))
    abort(2)
    assert (tm.available_size, pool.num_free_slots, len(cm.free_slots)) == counts

    for _ in range(4):
        step = scheduler._schedule_next_batch()
        _complete_on_cpu(scheduler, step)
        if any(req.uid == 3 for req in step.batch.reqs):
            break
    assert {req.uid for req in dm.running_reqs} == {1, 3}
    abort(1)
    abort(3)
    cm.check_integrity()

    # The cancelled request's retained prefix remains valid for a fresh session.
    next_wave = pending(4, 256, 32)
    next_wave.input_ids = torch.arange(2000, 2256, dtype=torch.int32)
    pm.pending_list.append(next_wave)
    scheduler.prefill_budget = 256
    step = scheduler._schedule_next_batch()
    req = step.batch.reqs[0]
    expected_hit = 192 if resume_chunk else 64
    assert req.cache_handle.cached_len == expected_hit and req.mamba_restore_src is not None
    source = {name: state.clone() for name, state in pool.state_views(req.mamba_restore_src)}
    scheduler._restore_linear_states(step.batch)
    for name, state in pool.state_views(req.linear_slot_idx):
        assert torch.equal(state, source[name])
    _complete_on_cpu(scheduler, step)
    abort(4)

    assert not pm.pending_list and not dm.running_reqs
    assert tm.available_size == 3 and len(set(tm._free_slots)) == 3
    assert cm.prefix_cache.full_protected == 0 and cm.prefix_cache.mamba_protected == 0
    assert pool.num_free_slots + cm.prefix_cache.mamba_evictable_size == pool.num_slots - 1
    assert len(set(pool._free_slots)) == pool.num_free_slots
    assert cm.available_size == cm.num_pages * page_size
    cm.check_integrity()
    assert all(msg.error == "request aborted" for msg in replies if isinstance(msg, ErrorReplyMsg))
