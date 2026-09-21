# Measurement protocol and historical results

The retained CSV/JSON includes unsuccessful profiles, warmup samples and invalid
runs with notes. Do not select the largest number from the whole CSV and call it
production speed. The final audit table is reported separately.

## Definitions

- **TTFT:** request start to the first nonempty reasoning/content/tool delta.
  An empty role SSE event is not a token.
- **Client decode rate:** `(completion_tokens - 1) / (last_nonempty_time - first_nonempty_time)`.
  This is the measured streaming interval, including reasoning tokens; it is
  not total-request throughput or GPU-kernel-only throughput.
- **End-to-end rate:** all completion tokens divided by the entire request time,
  including prefill. Always report this separately from decode.
- **Context:** distinguish configured total capacity from actual input usage.
  The selected capacity is 131072; real-code input is 104868/104870 tokens.
- **Fresh prompt:** cache reports zero reused prefix tokens. A restart followed
  by a fixed warmup and the same nonce sequence makes paired fresh comparisons.
- **Output budget:** 512 or 1024 tokens as recorded, `ignore_eos=true` for
  throughput tests; semantic checks use natural stopping.
- **Sampling:** explicit Medium; greedy temperature 0 for controlled trials,
  temperature 1 for a production-like sampled check. One active request.

Server API rates and client arrival rates agree for matched requests. For
example, the final pre-audit real-code request measured **41.4525 client** and
**41.4506 server** tok/s. The alleged universal 75K client/scheduler factor-of-two
gap was not reproduced. This does not deny issue #306 on its reported build.

Token timings are estimated from decoded SSE chunks. Long runs reduce boundary
effects; a chunk is not universally identical to one token. Use API usage as
the token count, not characters/second or a different model's tokenizer.

## Controlled baseline

| Stock profile | Actual input | Output | Decode tok/s | TTFT s | Prefix caveat |
|---|---:|---:|---:|---:|---|
| Hybrid, no MTP | 67 | 511 | 24.53 | 5.60 | Fresh |
| Hybrid, no MTP | 75068 | 511 | 24.53 | 59.85 | Fresh |
| Hybrid, no MTP | 105068 | 511 | 24.30 | 22.63 | 75008 tokens reused |
| Pure offload, no MTP | 105068 | 511 | 36.10 | See raw data | 75008 tokens reused |

The 105K stock controls used a shared nonce after the 75K run. Their decode
interval remains informative, but **their TTFT and end-to-end latency are not
comparable with fresh 105K MTP prompts**. An earlier `stock-hybrid` 75K sample
overlapped a build/profiler and is marked invalid, not used as the baseline.

## First optimization rounds

| Profile, fresh synthetic input about 105K | Decode tok/s | TTFT s |
|---|---:|---:|
| Kai MTP2, hybrid16, pinned PLE, 8K prefill | 47.96 | 73.37 |
| Kai MTP3, hybrid12, pinned PLE, 8K + D2D | 51.17 | 63.73 |
| Kai MTP5, hybrid12, 12K prefill | 48.58 | 44.91 |
| Kai MTP3, pure offload, 12K prefill | 29.29 | 45.14 |
| Kai MTP3, calibrated hybrid12, 12K | 51.05 | 45.01 |

These results selected MTP3 over deeper drafting and hybrid over pure offload
**with MTP**. They do not contradict pure offload beating the original no-MTP
hybrid: changing the speculative verification workload changes the optimum.
One initial sampled MTP2 run paid a 121-second JIT cost; it is not warm TTFT.

## Bounded real-code round

Same frozen prompt, 104868 input tokens, 1024 output, Medium and temperature 0:

| Variant | Decode tok/s | TTFT s | Total s |
|---|---:|---:|---:|
| MTP3, auto hybrid, CPU12, prefill12288 | 42.25 | 45.06 | 69.28 |
| Adaptive MTP2–4 | 41.11 | 47.96 | 72.84 |
| Fixed fetch4, CPU12 | 38.51 | 45.32 | See JSON |
| Fixed fetch8, CPU12 | 28.78 | 45.26 | See JSON |
| Fixed fetch4, CPU16 | 39.16 | 45.21 | See JSON |
| Prefill10240 | 41.61 | 54.92 | 79.51 |
| Prefill14336, selected | 42.50 | 40.34 | 64.42 |

Selection required >2% decode improvement to replace the baseline for adaptive
or manual hybrid. The prefill choice minimized total latency while retaining
at least 97% of baseline decode. Larger prefill improved TTFT by about 10.5%;
the 0.6% decode difference is not a meaningful isolated speedup claim.

## Pre-audit production confirmation from the Mac

| Workload | Actual input/output | Decode tok/s | TTFT s | Total s |
|---|---|---:|---:|---:|
| Real code, temperature0 | 104868 / 1024 | 41.45 | 41.24 | 65.92 |
| Real code, temperature1 | 104868 / 1024 | 38.06 | 40.34 | 67.23 |
| Synthetic LRU task, temperature0 | 105068 / 512 | 49.23 | 40.17 | 50.55 |
| Short task over SSH tunnel | 67 / 512 | 49.21 | 3.36 | 13.74 |

Synthetic decode versus the stock hybrid 105K control improved about 2.03x.
There is no stock real-code sample supporting a claim of 2x on all code tasks.
The aspirational 55–60 tok/s on real 100K+ code was not reached in this round.
Only two repeats in the audit and mostly single runs in earlier sweeps means
small percentage differences require restraint, not a statistical certainty claim.

The publication audit adds fresh paired results, new kernels and checks of the
remaining CPU/MTP settings. See `audit-results.md` and the machine-readable data
for those later measurements and the final production confirmation.
