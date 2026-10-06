# Concurrent serving validation — 2026-10-06

## Production selection

Select prefill-first with three active requests and exact graph ceiling 3. Paired sustained medians are 42.29/49.54/58.27 aggregate tokens/s for C=1/2/3 against 41.85/49.63/42.59 on the original service. The C=3 gain is 36.8%; C=1/2 remain close to control. Completed short-output waves also improve. The selection follows the user's preference for sustained generation over earlier first output. Fair is retained as an opt-in alternative; the separately screened 500 ms/graph-4 variant reduces long arrival pauses but does not improve C=3 sustained throughput. These are limited synthetic workload measurements, not a guarantee for every context size or real coding project.

Baseline Python runtime: `9fbe3b7`. Scheduler changes: `a7793dd`.
Scheduler plus asynchronous memory telemetry: `de46905`. These are measured
runtime content revisions; later launcher/documentation commits preserve the same Python core.

Single RTX 5090 with CPU expert offload; the checkpoint and its NVFP4 experts,
BF16 KV, FP32 recurrent states, pinned PLE and MTP depth 3 were kept fixed.
Serving window and shared KV reserve remain 262144 tokens. Active request cap
is 3, with 18 usable GDN slots and 2908 expert-cache slots. Memory ratio is
0.87, CPU expert workers 12, prefill ceiling 14336 tokens with auto chunks
observed at 13824–14336. Neither a V100 nor another GPU contributes.
Capacity is taken from `/v1/cache/status` geometry (4096 pages × 64).
The frontend stats page-size label is 1 in these snapshots; it is not
used to calculate token capacity or throughput.

## Sustained generation

Matched synthetic coding prompts with 1024 padding repetitions, Medium
reasoning, temperature 0, exactly 1024 generated tokens per request and EOS
ignored. Each repetition uses a distinct marker; payload hashes match across
profiles and launch logs confirm cache reporting is enabled. Prefix reports
are zero for these cold waves. These are short actual inputs under a 262K
reserve, not generation against a filled 262K conversation.

After all streams deliver nonempty output, exclude five seconds, then measure
a contiguous cumulative-token-counter interval while every client is still
active and unfinished. Retain at least five seconds and 32 generated tokens.
HTTP counter-read time lies between poll start/end; raw records contain
conservative rate bounds. Dividing aggregate rate by C gives an equal-share
average, not guaranteed per-user scheduling fairness.

| Profile | C | Repetitions | Aggregate tokens/s, median [range] | Aggregate/C |
|---|---:|---:|---:|---:|
| baseline-steady | 1 | 2 | 41.85 [41.45, 42.26] | 41.85 |
| baseline-steady | 2 | 2 | 49.63 [48.47, 50.79] | 24.81 |
| baseline-steady | 3 | 2 | 42.59 [42.47, 42.71] | 14.20 |
| fair500-graph4-steady | 1 | 2 | 41.44 [40.87, 42.01] | 41.44 |
| fair500-graph4-steady | 2 | 2 | 50.23 [48.71, 51.74] | 25.11 |
| fair500-graph4-steady | 3 | 2 | 40.84 [40.24, 41.43] | 13.61 |
| prefill-graph3-steady | 1 | 2 | 42.29 [41.91, 42.67] | 42.29 |
| prefill-graph3-steady | 2 | 2 | 49.54 [49.49, 49.59] | 24.77 |
| prefill-graph3-steady | 3 | 2 | 58.27 [57.97, 58.57] | 19.42 |

Observed statistics HTTP response times during sustained waves:

| Profile | Polls | Median ms | Maximum ms |
|---|---:|---:|---:|
| baseline-steady | 143 | 1998.55 | 2271.30 |
| fair1500-graph4-steady | 13 | 2027.95 | 2065.94 |
| fair500-graph4-steady | 676 | 3.32 | 5.60 |
| prefill-graph3-steady | 585 | 3.24 | 5.10 |

## Fixed short-output waves

Each request produces exactly 256 tokens. The baseline and final prefill-graph3
campaigns have three repetitions per matched cell. Fair500 is screened
with one short-wave repetition per cell and two sustained repetitions;
it is weaker evidence than the final profile campaign. Full-wave wall time includes all input preparation and
prefill; aggregate tokens/s is C×256 divided by that wall time. The new
telemetry fix changes HTTP delivery overhead too, so comparisons against
the original baseline measure the complete serving package. They do not
isolate graph or scheduling effects from telemetry.

| Profile | Padding | C | n | Wave seconds, median [range] | Aggregate tokens/s |
|---|---:|---:|---:|---:|---:|
| baseline-matched | 1024 | 1 | 3 | 14.07 [14.07, 14.43] | 18.20 |
| baseline-matched | 1024 | 2 | 3 | 23.38 [23.19, 23.67] | 21.90 |
| baseline-matched | 1024 | 3 | 3 | 28.79 [28.17, 31.22] | 26.68 |
| baseline-matched | 16384 | 1 | 3 | 20.81 [20.65, 20.89] | 12.30 |
| baseline-matched | 16384 | 2 | 3 | 28.48 [28.29, 30.34] | 17.98 |
| baseline-matched | 16384 | 3 | 3 | 40.57 [40.24, 42.60] | 18.93 |
| fair1500-graph4-matched | 1024 | 1 | 3 | 16.11 [14.02, 16.13] | 15.89 |
| fair1500-graph4-matched | 1024 | 2 | 3 | 25.79 [25.69, 25.99] | 19.85 |
| fair1500-graph4-matched | 1024 | 3 | 3 | 31.20 [30.97, 31.50] | 24.62 |
| fair1500-graph4-matched | 16384 | 1 | 3 | 20.60 [20.60, 21.04] | 12.43 |
| fair1500-graph4-matched | 16384 | 2 | 3 | 30.78 [30.18, 32.31] | 16.63 |
| fair1500-graph4-matched | 16384 | 3 | 3 | 44.89 [44.76, 45.05] | 17.11 |
| fair1500-matched | 1024 | 1 | 3 | 16.10 [14.04, 16.38] | 15.91 |
| fair1500-matched | 1024 | 2 | 3 | 26.06 [25.93, 26.20] | 19.64 |
| fair1500-matched | 1024 | 3 | 3 | 26.34 [26.04, 28.52] | 29.16 |
| fair1500-matched | 16384 | 1 | 3 | 20.71 [20.69, 20.94] | 12.36 |
| fair1500-matched | 16384 | 2 | 3 | 30.84 [30.79, 31.10] | 16.60 |
| fair1500-matched | 16384 | 3 | 3 | 40.53 [40.16, 40.69] | 18.95 |
| fair500-graph4-matched | 1024 | 1 | 1 | 12.76 [12.76, 12.76] | 20.05 |
| fair500-graph4-matched | 1024 | 2 | 1 | 21.58 [21.58, 21.58] | 23.72 |
| fair500-graph4-matched | 1024 | 3 | 1 | 28.60 [28.60, 28.60] | 26.85 |
| fair500-graph4-matched | 16384 | 1 | 1 | 17.88 [17.88, 17.88] | 14.31 |
| fair500-graph4-matched | 16384 | 2 | 1 | 27.21 [27.21, 27.21] | 18.82 |
| fair500-graph4-matched | 16384 | 3 | 1 | 41.64 [41.64, 41.64] | 18.44 |
| prefill-graph3-matched | 1024 | 1 | 3 | 12.74 [12.45, 12.79] | 20.10 |
| prefill-graph3-matched | 1024 | 2 | 3 | 21.51 [20.50, 21.55] | 23.80 |
| prefill-graph3-matched | 1024 | 3 | 3 | 23.23 [22.85, 23.65] | 33.06 |
| prefill-graph3-matched | 16384 | 1 | 3 | 17.80 [17.77, 18.06] | 14.38 |
| prefill-graph3-matched | 16384 | 2 | 3 | 26.90 [26.77, 27.11] | 19.04 |
| prefill-graph3-matched | 16384 | 3 | 3 | 35.30 [34.64, 35.39] | 21.76 |

## Delayed long arrivals and reused conversations

These workloads have matching shapes but timestamp markers differ; they are
not byte-identical paired prompts. An established 1K stream receives new
long input totalling 98304 padding repetitions. Its output is 512 tokens;
followers each generate 256. Baseline and 1500 ms profiles have two staggered
repetitions per cell; the 500 ms screening profile has one.
Warm cases have two turns, naturally stopping JSON output and one repetition
per cell. Positive cached-token reports establish prefix reuse.

| Profile | Mode | C | Turn | n | Wave seconds | First-stream max SSE gap, seconds |
|---|---|---:|---:|---:|---:|---:|
| baseline | staggered | 2 | 1 | 2 | 66.14 | 42.14 |
| baseline | staggered | 3 | 1 | 2 | 75.49 | 42.02 |
| baseline | warm | 2 | 1 | 1 | 20.94 | 5.34 |
| baseline | warm | 2 | 2 | 1 | 11.32 | 3.03 |
| baseline | warm | 3 | 1 | 1 | 28.90 | 10.62 |
| baseline | warm | 3 | 2 | 1 | 17.80 | 0.20 |
| fair1500 | staggered | 2 | 1 | 2 | 69.38 | 5.40 |
| fair1500 | staggered | 3 | 1 | 2 | 72.31 | 5.38 |
| fair1500 | warm | 2 | 1 | 1 | 22.67 | 5.34 |
| fair1500 | warm | 2 | 2 | 1 | 12.68 | 2.99 |
| fair1500 | warm | 3 | 1 | 1 | 30.14 | 5.37 |
| fair1500 | warm | 3 | 2 | 1 | 17.00 | 0.13 |
| fair1500-graph4 | staggered | 2 | 1 | 2 | 69.12 | 5.41 |
| fair1500-graph4 | staggered | 3 | 1 | 2 | 75.02 | 5.40 |
| fair1500-graph4 | warm | 2 | 1 | 1 | 22.58 | 5.31 |
| fair1500-graph4 | warm | 2 | 2 | 1 | 12.76 | 3.00 |
| fair1500-graph4 | warm | 3 | 1 | 1 | 31.06 | 5.40 |
| fair1500-graph4 | warm | 3 | 2 | 1 | 17.40 | 0.33 |
| fair500-graph4 | staggered | 2 | 1 | 1 | 66.29 | 5.40 |
| fair500-graph4 | staggered | 3 | 1 | 1 | 75.82 | 5.40 |
| prefill-graph3 | warm | 2 | 1 | 1 | 20.95 | 5.36 |
| prefill-graph3 | warm | 2 | 2 | 1 | 11.34 | 3.05 |
| prefill-graph3 | warm | 3 | 1 | 1 | 27.31 | 10.57 |
| prefill-graph3 | warm | 3 | 2 | 1 | 15.47 | 5.78 |

The 1500 ms fair policy reduces ~42-second established-stream pauses to
~5.4 seconds, but several fixed short-output cells become 8–11% slower
with graph 4. The user prioritizes sustained generation over earlier first
output; this latency improvement alone does not justify enabling fair by
default. Fair remains available as a separately configured tradeoff.
An executing prefill cannot be preempted; the burst budget is not an SSE
deadline. Two or more decoding requests use ordinary batched decode;
this release does not implement batched MTP.

## Correctness and resource checks

The expanded CPU gate on the frozen new runtime passed **274 tests**,
with 8 GPU-specific skips and 3 warnings, in 44.96 seconds. It covers
policy service budgets, scheduler interleaving, CLI validation, graph
ceilings, KV/GDN conservation, shared prefixes, in-flight cancellation,
terminal impossible admission, offline batch errors and asynchronous
single-flight memory metrics. Full-model serving checks below exercise
actual GPU capture/replay rather than substituting mock CPU tests.

| Profile | Structured tools | Mixed code/Russian/JSON | Semantic/MTP cases | Four queued clients | Accounting / idle / health |
|---|---:|---:|---:|---:|---|
| fair1500-graph4 | 3/3 | 3/3 | 9/9 | 4/4 | Passed |
| prefill-graph3 | 3/3 | 3/3 | 9/9 | 4/4 | Passed |

Each suite accounts for 19 completed requests and reconciles all input/output
tokens. Four clients share a cap of three active requests; the fourth
queues. Cancellation probes close a 96K victim only after a logged
completed partial-prefill chunk while a survivor is active. They require
one victim-specific abort, exactly one completed survivor with an exact
JSON record and usage-reconciled output, both prompts admitted once, unchanged instance,
healthy service and no remaining active GDN slots.

| Cancellation profile | Checks |
|---|---|
| fair1500 | 12/12 passed |
| fair1500-graph4 | 12/12 passed |
| prefill-graph3 | 12/12 passed |

These establish the recorded tasks and resource invariants. They do not
prove arbitrary coding quality or bit-identical generated text; different
expert-cache histories and existing hybrid CPU/GPU arithmetic can change
greedy trajectories. No model weights or precision were changed.

## Diagnostics, exclusions and reproducibility

Six `baseline-r2` exploratory cells overlapped an earlier CPU test run and
are retained as excluded diagnostics. Later baseline repetitions and the
matched campaign have no such competing test/build load. Older random-marker
graph-3 probes are exploratory and are not treated as matched-input speed proof.

The first long-output probe required <=1s statistics HTTP latency and could
not produce an accepted window on the original synchronous endpoint. The
stream, 1024-token budget and accounting passed; its raw response is retained
as a measurement diagnostic, separate from the paired v2 corpus. The revised
probe retains HTTP timestamps and uncertainty bounds instead of mistaking
a slow metrics endpoint for an inference failure.

The original `/v1/stats` read process-tree PSS synchronously for about two
seconds per poll. The new endpoint runs one scan in a thread and reuses a
ten-second snapshot; current request counters stay fresh. Host-memory age
and refresh state are explicit. Cold readers can wait for the initial
snapshot without blocking streams; warm readers do not wait during refresh.

The [data file](../../benchmarks/rtx5090/data/concurrency-results-20261006.json)
contains sanitized per-request usage/timing, payload hashes, counter deltas,
steady interval endpoints and derived distributions. Response text, private
endpoints and host filesystem paths are omitted.
[verify_artifacts.py](../../benchmarks/rtx5090/verify_artifacts.py) recomputes
rate arithmetic, medians, payload identity and accounting without a GPU.
Use the [probe README](../../benchmarks/rtx5090/README.md) and
[concurrency guide](CONCURRENCY.md) for exact commands and controls.

No four-active-request, GDN host-tier or lower-state-cache-ratio performance
claim is made. The 262144-token KV pool is shared across active contexts
and retained prefixes; transient capacity pressure queues, while a
request whose rounded input plus output cannot fit the entire ordinary
pool receives a terminal context-length error.
