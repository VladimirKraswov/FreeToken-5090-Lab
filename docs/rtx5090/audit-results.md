# Publication audit, 2026-09-21

All real-code comparisons use the frozen fixture, 104870 input tokens,
1024 output tokens, explicit Medium and temperature 0 unless stated.
Measurements are taken by the same Mac client. Each variant is restarted
and warmed before its nonce sequence. Full individual rows are in
[all-results.csv](../../benchmarks/rtx5090/data/all-results.csv).

| Profile | Repeats | Decode mean (range), tok/s | Mean TTFT, s | Mean total, s |
|---|---:|---:|---:|---:|
| audit-baseline | 2 | 41.94 (41.74–42.15) | 40.31 | 64.70 |
| audit-cpu16 | 2 | 42.95 (42.46–43.44) | 40.45 | 64.27 |
| audit-cpu8 | 2 | 38.33 (37.88–38.79) | 40.57 | 67.26 |
| audit-fused | 2 | 42.79 (42.43–43.14) | 40.47 | 64.38 |
| audit-mtp2 | 2 | 40.31 (39.97–40.65) | 40.53 | 65.91 |

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
