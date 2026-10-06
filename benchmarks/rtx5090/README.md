# RTX 5090 benchmark package

- `stream_bench.py`: stdlib streaming client, local or remote endpoint, gzip fixture support.
- `validate_final.py`: long-context retrieval, Vision, tools and Responses checks.
- `warmup.py`: the boot/restart warmup used by the deployment template.
- `verify_artifacts.py`: checks raw metric arithmetic, fixture identity and publication hygiene.
- `fixtures/`: immutable Apache-2.0 real-code prompt and its provenance.
- `data/all-results.csv`: combined historical and publication-audit table, including failed streams.
- `data/all-results.json`: the same full-precision table in JSON.
- `data/pre-audit-results.csv`: all 67 completed historical measurements, including marked invalid/warmup rows.
- `data/results/`: raw per-run measurements; three historical incomplete streams are retained as failures.
- `data/historical-profiles.json`: original profile settings, including discarded variants.
- `data/pre-audit-bounded-round.json`: paired real-code tuning round and selection.
- `data/model-manifest.json`: pinned checkpoint filenames, sizes and Hugging Face metadata.
- `data/runtime-versions.json`: measured Python package inventory.
- `data/strata-results-20261005.json`: controlled Strata-inspired trials, exclusions and restoration evidence.
- `data/concurrency-results-20261006.json`: paired concurrent serving, steady counter windows and correctness evidence.
- `data/research-index.json`: dated branch/issue discovery references.
- `data/tests/`: regression failures before fixes and passing CPU/GPU test results.

Read [the measurement guide](../../docs/rtx5090/measurement.md) before comparing rows.
TTFT from a cached prompt, a JIT warmup, and a fresh prompt are different metrics.
Audit and final-production results are added alongside the historical campaign.

```bash
python benchmarks/rtx5090/verify_artifacts.py
```

The [Strata trial report](../../docs/rtx5090/STRATA_VALIDATION_20261005.md) records rejected prototypes as well as the production decision.

## Concurrent-session probes

The scripts below use Python's standard library and make real streaming API
requests. Run them sequentially against a dedicated, warmed server with
`--enable-cache-report`. They reject existing active work and verify completion
accounting, but do not lock the server against another client arriving later.
Record the revision, exact launch command, captured graph sizes and resolved
KV/GDN/expert-cache geometry separately for every profile.

The [concurrency guide](../../docs/rtx5090/CONCURRENCY.md) describes the controls.
For a scheduler-only comparison, keep the graph ceiling, active-request limit,
prefill chunk and memory geometry identical. Change only
`--scheduler-policy prefill-first` to `--scheduler-policy fair` and its two burst
budgets. For example, `--scheduler-decode-burst-ms 1500
--scheduler-decode-burst-steps 64` is an experimental profile, not a production
recommendation. The fair policy serves one prefill batch followed by a bounded
generation burst; MTP verification counts as generation. A running prefill
cannot be interrupted, and the burst time budget is checked after each complete
batch. It is not a bound on SSE gaps or request cancellation latency.

### Fixed work and JSON isolation

`concurrency_fixed.py` starts requests through a barrier. Its default throughput
case requests exactly 256 output tokens with EOS ignored. `--quality` instead
allows natural stopping and checks an exact per-session JSON record with a
marker, retrieval needle and arithmetic result. It targets the served model
name `qwen38-flash-next`.

```bash
python benchmarks/rtx5090/concurrency_fixed.py \
  --base http://127.0.0.1:1919 --profile control \
  --corpus-seed concurrency-v1 --repeat 1 \
  --lengths 1024,16384 --counts 1,2,3 --tokens 256 \
  --out outputs/concurrency/control/r1/fixed

python benchmarks/rtx5090/concurrency_fixed.py \
  --base http://127.0.0.1:1919 --profile control-json \
  --corpus-seed concurrency-v1 --repeat 1 \
  --lengths 1024,16384 --counts 1,2,3 --quality \
  --out outputs/concurrency/control/r1/json
```

Use the same seed, repeat, padding and concurrency on each profile after its
restart. These determine the prompt independently of the profile label; compare
the saved payload/prompt SHA-256 values before treating rows as matched. Change
the repeat number for each repetition and use a separate output directory:
filenames do not include the repeat number and otherwise overwrite prior rows.
Do not rerun the same cold corpus against an unchanged cache and call it another
cold repetition. `--lengths` specifies padding repetitions; use actual
`usage.prompt_tokens` for input-token counts.

The reports contain per-request timing and usage, cache hits, stream completion,
whole-wave aggregate tokens/s and before/after counters. A zero cached-token
field establishes a cold result only when cache reporting is enabled. Natural
JSON responses have different output lengths from the fixed-work probe; compare
their correctness separately from fixed-work throughput.

### Sustained generation after prefill

For longer fixed output, `--require-steady` requires a measured window from
frontend cumulative completion-token counters. The window starts at least five
seconds after every stream has delivered its first nonempty output and all
prompt tokens have been accounted for, while all C requests
remain unfinished and active. It requires at least five seconds and 32 generated
tokens, a contiguous sequence of polls no more than five seconds apart, and
individual HTTP poll latency at most three seconds. Prompt accounting alone marks admission and does not prove completed prefill;
requiring output from every stream provides that barrier. The first/last snapshots and
counts are saved for independent arithmetic verification. Poll start/end times
also yield lower/upper rate bounds, since a counter was read somewhere within
that HTTP interval; slow control endpoints make these bounds wider. These bounds can
leave no usable window on a short response, so the default 256-token probe does
not require one.

```bash
python benchmarks/rtx5090/concurrency_fixed.py \
  --base http://127.0.0.1:1919 --profile control-steady-r1 \
  --corpus-seed concurrency-steady-v1 --repeat 1 \
  --lengths 1024 --counts 1,2,3 --tokens 1024 --require-steady \
  --out outputs/concurrency/control/steady/r1
```

`aggregate_tps` counts all active sessions together. Dividing it by C gives
`per_active_request_tps`, an equal-share average rather than proof of identical
per-session service. This metric excludes the initial prefill and parser-induced
SSE buffering; complete-wave latency still includes all scheduling and input
costs. Keep the steady corpus separate from the 256-token corpus, since output
budget is not part of the version-1 corpus nonce.

### Delayed arrivals and conversation follow-ups

`concurrency_latency.py --mode staggered` begins one short prompt, then sends
the other long prompts only after the first stream emits nonempty content or
reasoning. This exercises prefill arriving during established generation. The
first request has a fixed 512-token output and the others 256 tokens each.
`--mode warm` runs two turns per session with natural stopping, checks each
session's JSON record, and records whether follow-ups report cached tokens.

```bash
python benchmarks/rtx5090/concurrency_latency.py \
  --base http://127.0.0.1:1919 --profile control \
  --mode staggered --counts 2,3 --repeats 3 \
  --out outputs/concurrency/control/staggered

python benchmarks/rtx5090/concurrency_latency.py \
  --base http://127.0.0.1:1919 --profile control \
  --mode warm --counts 2,3 --repeats 3 \
  --out outputs/concurrency/control/warm
```

These two modes use a fresh timestamp marker on each run; they exercise matched
workload shapes but do not use byte-identical prompts across profiles. Report
TTFT and per-stream p95/p99/maximum gaps together with complete request timing.
The events are nonempty SSE fragments, including reasoning, and can contain
multiple tokens or be delayed by parser buffering. They measure client-visible
delivery, not individual kernel latency. Small samples and synthetic repeated
padding do not establish a general latency or coding-quality guarantee.

### Disconnect and recovery

Run `concurrency_cancel.py` on the server host against an HTTP localhost origin,
with permission to read the service's systemd journal. It first starts a survivor
that must return a long, exact JSON record containing 256 values. Once that
stream produces output, it submits the long victim prompt and reads its numeric
request UID from the initial SSE event.

The probe waits for a completed partial-prefill journal entry with one running
request and one queued request, checks that both are still active, then closes
the victim socket. The survivor must have started streaming before the close
and finish after it. Select the actual service unit with `--journal-unit`:

```bash
python benchmarks/rtx5090/concurrency_cancel.py \
  --base http://127.0.0.1:1919 \
  --journal-unit freetoken-qwen.service \
  --out outputs/concurrency/control/cancel.json
```

The saved report requires exactly one victim-specific abort log after the
close, exactly one completed request, and generated-token counters attributable
only to the survivor. Both full prompts must be admitted once, the victim's
prompt must exceed the observed chunk, and the service must return to idle with
no active GDN slots, the same instance ID and healthy status. There is no public
aborted-request counter, so the report retains the UID-specific journal evidence
and accounting deltas explicitly. The output directory is created if needed.

This establishes cancellation after an observed unfinished prefill and
overlapping survivor activity. It does not claim to interrupt an executing GPU
kernel or enforce a cancellation deadline.

Retain failures and raw reports. Use repeated controls and candidates to assess
throughput and latency together; graph changes, chunk-size changes and GDN
memory changes require separate comparisons. Passing these probes establishes
the observed completion, accounting and task checks only. It does not prove
identical generated text, arbitrary tool correctness, or unchanged quality on
all prompts. A production selection needs measured results and an explicit
record of the chosen launch configuration.
