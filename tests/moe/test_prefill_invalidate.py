"""Prefill buffer invalidation must preserve mappings without a host-dependent shape."""

from types import SimpleNamespace

import pytest
import torch

from freetoken.moe.offload_cache import OffloadMoeCache


def cache(device, experts=8):
    return SimpleNamespace(
        num_experts=experts,
        device=torch.device(device),
        id_of_slot=torch.full((experts * 3,), -1, dtype=torch.int32, device=device),
        slot_for_id=torch.full((3, experts), -1, dtype=torch.int32, device=device),
        usage=torch.arange(experts * 3, dtype=torch.int64, device=device) + 1,
    )


def seed(c, buffer_id):
    e = c.num_experts
    slots = torch.arange(e, device=c.device) + buffer_id * e
    ids = (torch.arange(e, device=c.device) * 3 + 1) % (e * 3)
    c.id_of_slot[slots] = ids.to(torch.int32)
    c.slot_for_id.view(-1)[ids.long()] = slots.to(torch.int32)
    c.id_of_slot[slots[::2]] = -1
    c.slot_for_id.view(-1)[ids[::2].long()] = -1


@pytest.mark.parametrize("device", ["cpu", "cuda"])
@pytest.mark.parametrize("buffer_id", [0, 1])
@pytest.mark.parametrize("experts", [8, 257, 512])
def test_invalidation_matches_reference(device, buffer_id, experts):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("needs CUDA")
    c = cache(device, experts)
    seed(c, buffer_id)
    expected_ids = c.id_of_slot.clone()
    expected_map = c.slot_for_id.clone()
    expected_usage = c.usage.clone()
    span = slice(buffer_id * experts, (buffer_id + 1) * experts)
    old = expected_ids[span]
    expected_map.view(-1)[old[old >= 0].long()] = -1
    old.fill_(-1)
    expected_usage[span].zero_()
    OffloadMoeCache._invalidate_prefill_buffer(c, buffer_id)
    assert torch.equal(c.id_of_slot, expected_ids)
    assert torch.equal(c.slot_for_id, expected_map)
    assert torch.equal(c.usage, expected_usage)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs CUDA")
def test_invalidation_has_no_data_dependent_nonzero():
    c = cache("cuda")
    seed(c, 0)
    OffloadMoeCache._invalidate_prefill_buffer(c, 0)  # JIT outside the measurement
    seed(c, 0)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU]) as prof:
        OffloadMoeCache._invalidate_prefill_buffer(c, 0)
    assert not any("nonzero" in event.key for event in prof.key_averages())


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs CUDA")
def test_invalidation_replays_with_new_mapping_values():
    c = cache("cuda")
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        OffloadMoeCache._invalidate_prefill_buffer(c, 1)
    torch.cuda.current_stream().wait_stream(stream)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph, stream=stream):
        OffloadMoeCache._invalidate_prefill_buffer(c, 1)
    for _ in range(3):
        seed(c, 1)
        graph.replay()
        assert torch.all(c.id_of_slot[8:16] == -1)
        assert torch.all(c.slot_for_id == -1)
        assert torch.all(c.usage[8:16] == 0)
