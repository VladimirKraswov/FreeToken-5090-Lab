# Publication audit, 2026-09-21

Real-code comparisons use the frozen fixture and 104870 input tokens.
All requests explicitly select Medium; output length and temperature are shown.
Measurements are taken by the same Mac client. Each variant is restarted
and warmed before its nonce sequence. Full individual rows are in
[all-results.csv](../../benchmarks/rtx5090/data/all-results.csv).

| Profile | Input / output tokens | Temp. | Repeats | Decode mean (range), tok/s | Mean TTFT, s | Mean total, s |
|---|---:|---:|---:|---:|---:|---:|
| audit-baseline | 104870 / 1024 | 0 | 2 | 41.94 (41.74–42.15) | 40.31 | 64.70 |
| audit-cpu16 | 104870 / 1024 | 0 | 2 | 42.95 (42.46–43.44) | 40.45 | 64.27 |
| audit-cpu8 | 104870 / 1024 | 0 | 2 | 38.33 (37.88–38.79) | 40.57 | 67.26 |
| audit-final-real | 104870 / 1024 | 0 | 2 | 42.59 (42.08–43.09) | 40.48 | 64.51 |
| audit-final-sampled | 104870 / 1024 | 1 | 2 | 37.86 (36.39–39.34) | 40.06 | 67.12 |
| audit-final-synthetic | 69 / 512 | 0 | 1 | 49.68 (49.68–49.68) | 3.50 | 13.79 |
| audit-final-synthetic | 105070 / 512 | 0 | 1 | 48.93 (48.93–48.93) | 39.95 | 50.39 |
| audit-fused | 104870 / 1024 | 0 | 2 | 42.79 (42.43–43.14) | 40.47 | 64.38 |
| audit-mtp2 | 104870 / 1024 | 0 | 2 | 40.31 (39.97–40.65) | 40.53 | 65.91 |

Profile definitions:

- `audit-baseline`: the completed pre-audit MTP3/CPU12/prefill14336 profile.
- `audit-fused`: PLE hash + fixed-shape prefill invalidation; same configuration.
  These short measurements preceded the graph-input lifetime hardening; they did
  not churn enough shapes to hit that defect. Do not deploy the uncorrected patch.
- `audit-cpu8`, `audit-cpu16`: final hardened source, MTP3, only CPU worker count changes.
- `audit-mtp2`: final hardened source, CPU12, only MTP depth changes.
- `audit-final-*`: final production confirmation; names identify workload and sampling.

The first fused-kernel pair averaged about 2% faster decode than the old pair,
while TTFT was essentially unchanged. With two repeats and small absolute
differences, this is not evidence of a guaranteed 2% improvement. The larger
earlier gains came from MTP, memory lifetime fixes and the selected profile.

Checks include the 135-pass focused CPU/GPU suite, four documented optional
skips, two CPU-only streaming-harness tests, and checksum/arithmetic checks.
The graph-index lifetime regression fails before its fix and passes afterward.
See [changes.md](changes.md) for the unchanged baseline CPU/BLAS test caveat.

## Selection and final functional checks

Keep **MTP3, CPU12, calibrated hybrid, prefill14336, D2D, pinned PLE,
Triton NVFP4**, context131072 and BF16 KV. CPU16's 0.37% advantage over the
initial fused CPU12 pair is within run-to-run variation, below the predeclared
2% promotion threshold. CPU8 and MTP2 are slower. The repeated final CPU12 pair
also remains in the same range. Adaptive MTP stays off.

Final validation on the restored production process passed:

- Exact retrieval of three values from the start/middle/end of **105077 input tokens**.
- Vision: **2048x2048**, 4096 image tokens / **4120 total prompt tokens**, answer `Red`.
- Structured `get_weather` call with `Moscow` and `tool_calls` finish reason.
- Responses API: `READY`, completed.
- Automatic warmup covers greedy, sampling, **16019 prompt tokens** and Vision.
- Service and watchdog enabled/active, zero automatic restarts and no fresh
  host/guest PCIe/AER/Xid/IOMMU errors during the audit scan.
- Final idle NVML: **31850 MiB used**, 262 MiB free; power cap500W.
  Gen3 x16 was observed under load; Gen1 x16 at idle is normal.

These are functional checks, not a comprehensive quality evaluation. Detailed
payload results and warmup/health observations are in `data/audit-final-*.json`
and `data/hardware-observations.json`. The model remains loaded; the media VM
is stopped. The engine source hashes match the published fork.
