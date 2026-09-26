"""Validate one real Qwen3.8 NVFP4 expert on a Volta GPU without loading the model."""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import time

import torch
from safetensors import safe_open

from freetoken.moe.fused_nvfp4 import fused_experts_decode_nvfp4_marlin


E2M1 = torch.tensor(
    [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0,
     -0.0, -0.5, -1.0, -1.5, -2.0, -3.0, -4.0, -6.0]
)


def load_projection(reader, *, layer: int, expert: int, projection: str):
    stem = f"model.language_model.layers.{layer}.mlp.experts.{expert}.{projection}"
    codes = reader.get_tensor(f"{stem}.weight").unsqueeze(0).cuda()
    scales = reader.get_tensor(f"{stem}.weight_scale").unsqueeze(0).cuda()
    global_scale = reader.get_tensor(f"{stem}.weight_scale_2")
    rows = codes.shape[1]
    global_rows = global_scale.expand(1, rows).to(torch.float16).cuda()
    return codes, scales, global_rows


def dequant(projection):
    codes, scales, global_rows = projection
    packed = codes[0]
    n, k2 = packed.shape
    indices = torch.stack((packed & 15, packed >> 4), dim=-1).reshape(n, 2 * k2).long()
    return (E2M1.to(packed.device)[indices]
            * scales[0].float().repeat_interleave(16, dim=1)
            * global_rows[0].float()[:, None])


def run(model: Path, layer: int, expert: int, count: int, bench_steps: int) -> None:
    if count < 1 or expert < 0 or expert + count > 512 or expert // 128 != (expert + count - 1) // 128:
        raise ValueError("the expert range must fit in one 128-expert shard")
    shard = model / f"layer-{layer:05d}-experts-{expert // 128 * 128:04d}-{expert // 128 * 128 + 127:04d}.safetensors"
    with safe_open(shard, framework="pt", device="cpu") as reader:
        def bank(projection):
            pieces = [load_projection(reader, layer=layer, expert=e, projection=projection)
                      for e in range(expert, expert + count)]
            return tuple(torch.cat([piece[i] for piece in pieces], dim=0) for i in range(3))

        gate = bank("gate_proj")
        up = bank("up_proj")
        down = bank("down_proj")

    gate_up = tuple(torch.cat((g, u), dim=1) for g, u in zip(gate, up))
    torch.manual_seed(31)
    hidden = (torch.randn(1, gate[0].shape[-1] * 2, device="cuda") / 4).to(torch.float16)
    ids = torch.arange(count, dtype=torch.int32, device="cuda").reshape(1, count)
    weights = torch.full((1, count), 1 / count, dtype=torch.float32, device="cuda")
    actual = fused_experts_decode_nvfp4_marlin(
        hidden, *gate_up, *down, weights, ids, "silu", False
    )

    reference = torch.zeros(hidden.shape[1], device="cuda", dtype=torch.float32)
    for j in range(count):
        gu = tuple(t[j:j + 1] for t in gate_up)
        dn = tuple(t[j:j + 1] for t in down)
        h = dequant(gu) @ hidden[0].float()
        i = h.numel() // 2
        reference += (dequant(dn) @ (torch.nn.functional.silu(h[:i]) * h[i:])) / count
    difference = (actual[0].float() - reference).abs()
    tolerance = 0.03 * reference.abs().max() + 1e-4
    print(f"layer={layer} expert={expert} count={count} max_abs_error={difference.max().item():.6g} "
          f"tolerance={tolerance.item():.6g} reference_max={reference.abs().max().item():.6g}")
    if difference.max() > tolerance:
        raise AssertionError("NVFP4 Volta expert differs from the float32 dequant reference")

    if bench_steps:
        for _ in range(10):
            fused_experts_decode_nvfp4_marlin(hidden, *gate_up, *down, weights, ids, "silu", False)
        torch.cuda.synchronize()
        elapsed_ms = []
        for _ in range(bench_steps):
            started = time.perf_counter()
            fused_experts_decode_nvfp4_marlin(hidden, *gate_up, *down, weights, ids, "silu", False)
            torch.cuda.synchronize()
            elapsed_ms.append((time.perf_counter() - started) * 1000)
        print(f"moe_wall_ms median={statistics.median(elapsed_ms):.3f} "
              f"min={min(elapsed_ms):.3f} steps={bench_steps}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--layer", type=int, default=0)
    parser.add_argument("--expert", type=int, default=0)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--bench-steps", type=int, default=0)
    options = parser.parse_args()
    run(options.model, options.layer, options.expert, options.count, options.bench_steps)
