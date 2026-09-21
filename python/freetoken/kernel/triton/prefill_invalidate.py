# SPDX-License-Identifier: Apache-2.0
"""Invalidate borrowed MoE slots without a dynamic-shape boolean gather."""

import triton
import triton.language as tl


@triton.jit
def _invalidate(ids, mapping, usage, START: tl.constexpr, COUNT: tl.constexpr, BLOCK: tl.constexpr):
    index = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    valid = index < COUNT
    slot = START + index
    expert = tl.load(ids + slot, mask=valid, other=-1)
    # Resident expert ids are unique across slots; each mapping has one writer.
    tl.store(mapping + expert, -1, mask=valid & (expert >= 0))
    tl.store(ids + slot, -1, mask=valid)
    tl.store(usage + slot, 0, mask=valid)


def invalidate_prefill_buffer(id_of_slot, slot_for_id, usage, start: int, count: int):
    if count:
        _invalidate[(triton.cdiv(count, 256),)](
            id_of_slot, slot_for_id, usage, START=start, COUNT=count, BLOCK=256,
        )
