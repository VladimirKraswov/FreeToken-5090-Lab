# Strata-inspired optimization experiments, 2026-10-05

The reference serving build is `6ae2ccf2e26ed713729e8f6f149f28b5771d248d`.
These trials keep the existing Qwen3.8-Flash-Next NVFP4 checkpoint, BF16 KV,
262144-token total window, one RTX 5090, 12 CPU expert workers and target
sampling/acceptance rule. No weights, expert precision, thinking budget or
context capacity were reduced to improve a benchmark score.

The investigated Strata revision is
[`6f32ec070f23ced9f50e704d854d775da52591ab`](https://github.com/Niko1221/Strata/tree/6f32ec070f23ced9f50e704d854d775da52591ab).
Its own speed figures use a different engine, quantization and host platform;
they are not a matched baseline for this machine.

## Protocol

Each full profile starts a fresh model process, completes the normal warmup,
and then runs three 1024-output-token repetitions of each frozen fixture:

- `edit`: 11713 input tokens, greedy, thinking off.
- `long-code`: 104870 input tokens, temperature 1, Medium reasoning.

The same per-case/per-repetition nonce is reused between profiles. It fixes
prompt identity, not the target sampler's random seed. Decode is the client
streaming rate `(completion_tokens - 1) / (last_token_time - first_token_time)`.
TTFT and whole-request latency are reported separately. Full-profile semantic
screens cover all nine existing cases, including bounded output tails, natural
stopping, JSON and tool behavior. They are a regression screen, not a broad
reasoning-quality benchmark.

An initial baseline short-code repetition overlapped CPU-only compilation and
is excluded from performance aggregation. It remains in the retained evidence.
Other full-model measurements have no concurrent test/build workload.

Every driver uses one process lock and an owned temporary systemd override;
its exit handler removes that override and checks that the original service
configuration, health and warmup instance have been restored. Failed compilation,
native-extension setup and an early truncated-window controller bug are recorded
as failures, not benchmark results.

## Investigated changes

### Exact clustered QSA selection

Prototype v1 independently implemented clustered selection; v2 adapted Strata's
push-histogram/PTX scan and retains Strata's MIT notice. Tests cover exact ordering,
ties, NaN/invalid candidates, ragged visible lengths and CUDA graph replay.
No sparse-attention selection semantics were relaxed.

The production engine already has a parallel Triton split/merge implementation.
V1 was roughly twice as slow in the isolated kernel. V2 approached parity at
65536 columns but was slower at 8192 and 32768. Whole-model v1 measurements did
not show a useful gain. A large gain over Strata's former serial implementation
therefore did not transfer to this baseline.

### Cost-aware MTP depth

A per-request controller measures committed tokens per elapsed millisecond,
including verification, rollback and next-draft generation. It explores captured
depths, uses smoothed rewards and a 3% switching margin. Transition steps and
truncated final windows are excluded from learning. The target sampler and
acceptance rule are unchanged.

Capturing depths 2/3/4 added graph memory and reduced the effective prefill chunk
from 14336 to 11520. The 11713-token fixture then needed two prefill chunks;
its median TTFT rose from about 5.3 to 14.8 seconds. A short decode gain did not
compensate for that latency or for slower long-code generation. A narrower 3/4
controller and fixed depths 2 and 4 were tested separately before selection.

### Shared speculative CUDA graph pool

A graph-pool-sharing prototype failed its GPU regression before model throughput
measurement: replay overwrote another graph's persistent output buffers. It was
rejected. Merely sharing an allocator pool is not safe when graph output lifetimes
and arbitrary depth replay order are not guaranteed. No shared-pool runtime code
is included in the selected release.

## Retained correctness coverage

PLE rollback tests now cover every valid accepted prefix for verify windows of
3, 4 and 5 rows, including repeated graph replay, changed slots and subsequent
convolution output. The wider coverage is useful independently of whether a
new MTP policy is fast enough to deploy. Invalid combinations are not generated
or counted as skipped passes.

## Measurements and release decision

Final measurements and the selected production configuration are recorded below.
The sanitized machine-readable evidence is
[`strata-results-20261005.json`](../../benchmarks/rtx5090/data/strata-results-20261005.json).

| Profile | Edit decode tok/s | Edit TTFT s | Long-code decode tok/s | Long-code TTFT s |
|---|---:|---:|---:|---:|
| MTP3, initial baseline | 43.01 | 5.24 | 33.48 | 41.95 |
| Clustered QSA v1 | 43.20 | 5.24 | 33.25 | 41.98 |
| Timed MTP2/3/4 | 44.82 | 14.76 | 32.36 | 52.10 |
| MTP3, paired control | 42.93 | 5.26 | 33.50 | 42.09 |
| Fixed MTP2 | 39.96 | 5.23 | 32.35 | 41.90 |
| Fixed MTP4 | 45.45 | 5.25 | 31.59 | 41.94 |
| MTP3, final control | 43.11 | 5.25 | 33.67 | 42.04 |
| Timed MTP3/4 | 45.10 | 5.24 | 32.22 | 47.04 |

These are medians of three repetitions, except the first baseline edit median,
which excludes the one interfered repetition described above. A sampled output
need not have the same hash after changing draft depth: the nonce is not an RNG
seed. All retained greedy edit replies match the baseline byte-for-byte.

The timed3/4 focused GPU suite passed **117 tests**, with **4 skips** for optional
reference/weight fixtures. Cluster v2 separately passed 35 GPU kernel cases.
The shared-pool screen failed before throughput measurement and is not called
a model benchmark. Failed prototypes are preserved locally with source patches,
source hashes and complete logs, rather than installed as serving code.

### Decision

No new runtime optimization passed the promotion gate: a median decode gain of
at least 3% in one fixture, no more than 2% regression in the other, passing
semantic screens and a confirming run. In particular, fixed MTP4 gains about
5.4% on the greedy short fixture but loses about 6.2% on long sampled code;
timed policies also consume more prefill memory and increase long-request latency.
Short-fixture gains must not be described as a general model acceleration.

The production path remains fixed **MTP3**, full **262144** context and **BF16 KV**.
Only the broader PLE rollback regressions, these measured results, artifact
verification and documentation are merged into main. Serving Python and native
extensions are unchanged, so deploying this documentation/test revision does
not require another model restart. The final restoration checks verify the
normal service configuration and the matching healthy/warm model instance.

The finite semantic screen does not prove unchanged quality on every reasoning
task. Since no experimental runtime was selected, this release changes no model
inference behavior. Future graph memory work must preallocate and isolate all
persistent state/output buffers before considering pool sharing; coupled random
sampling would require its own sampler and distribution/correctness audit.
