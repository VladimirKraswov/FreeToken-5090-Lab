# What changed and why

Base: FreeToken-Kai `c206a6dfc614e983c57f71da391ff4ee76289ed2`, incorporating
FlashML FreeToken `cc1f5c2c91855f2cc7787ad6b909f7e46a5d5825`.

## PLE state correctness, 2026-10-01

The speculative verify pass advanced PLE convolution history through rejected
draft tokens. Rollback already restored GDN state and PLE n-gram context, but
omitted this convolution history. `SpecPleStash` now saves the pre-window state
and convolution inputs and restores only the accepted prefix. The default is
enabled; `FT_SPEC_PLE_ROLLBACK=0` is only an A/B diagnostic for the old behavior.

CPU regressions fail on the original main and pass with the fix. CUDA graph tests
cover accepted lengths 1-4, new replay inputs, slot changes and the next
convolution output. A separate test-fixture fix prevents host-embedding CPU RoPE
caches from leaking into GPU cases. The selected release suite has 181 passes,
48 skips and 2 deselections; skips are not claimed as passes.

Prompt lookup and reuse-aware fetch prototypes were tested separately and are
not included in main. Their throughput observations must not be attributed to
this correctness-only release. See the [validation report](MTP_VALIDATION_20260930.md)
for matched measurements, serving checks and their limits.

## Our initial engine changes

### Bounded PLE rollback work

MTP rollback called `req.input_ids.tolist()` and then copied the full history
again to construct a two-token PLE n-gram context. At 100K+ context that puts
O(context) host work on every verify step. `ngram_context_after` now reads only
the required tail of the committed tensor and accepted drafts. Its output is
unchanged, including boundary padding and zero-length contexts.

Tests include a history object that rejects whole-history iteration and 64
reference cases spanning short histories and 105083 tokens. The bounded-read
regression fails on the old implementation. A helper microbenchmark is not
presented as a whole-model throughput gain.

### Shorter lifetimes for prefill temporaries

`Qwen4ExpMTP.forward` retained normalization/projection buffers through the
expert GEMM allocation peak. `PLELayer.forward` similarly retained embeddings,
keys, queries, values and gates after forming the convolution input. Explicitly
dropping these dead references reduces overlap of temporary allocations.
Tensor arithmetic and target weights are unchanged. Weak-reference regressions
verify release before the next peak and check output values. This enabled larger
prefill chunks without lowering context or KV precision.

### Experimental adaptive MTP

`FT_SPEC_ADAPTIVE=1` with `--spec-mtp 4`, one GPU and QSA captures verify windows
for depths 2, 3 and 4. A request starts at depth 3. Every eight verification
steps, accepted draft tokens divided by proposed drafts selects a higher depth
at >=85%, a lower depth at <=60%, or holds. The mandatory target sample is
excluded from acceptance. State is per request.

Each graph retains its own attention-addressing buffers; replay must stage the
same buffers that capture recorded. Both eager and graph draft loops use the
selected depth, and shortened tail windows retain the eager fallback.

This controller was tested but **is off in production**: 41.11 versus 42.25 tok/s
on the first real-code comparison. It is not advertised as superior to a
cost-aware controller or as validated on every model/backend. Fixed MTP=3 is
the normal selected path. It does not require the experimental environment flag.

## Changes found during the publication audit

### Fused PLE row hashing — adopted, not invented here

The implementation and tests come from **dejay2**, upstream
[PR #338](https://github.com/FlashML-org/FreeToken/pull/338), commit
`de77d16a5ac36494d85964f846b50ad36f7acc21`. Author attribution is retained in git.
It computes exact integer row IDs in one Triton kernel and preserves a torch
reference/CPU fallback. Tests cover boundary handling, negative remainder
semantics, shape-cache identity, and graph replay with changing inputs.

`FREETOKEN_PLE_FUSED_HASH=0` restores the reference path for A/B testing.
This model has one PLE layer, so a dramatic helper-kernel speedup must not be
reported as a dramatic overall decode gain.

During integration we found and fixed a buffer-lifetime defect in that patch.
The bounded eager shape cache could evict an index tensor that a CUDA graph
already referenced. Graph capture preserves device addresses, not the Python
ownership of external tensors. We retain immutable indices used by captured
graphs separately for the model lifetime; eager-only shapes still use a bounded
cache. The graph test now churns through more than the cache limit before
replaying with new tokens. Its weak-reference check fails on the original PR
implementation and passes with the ownership fix, before any unsafe replay.

### Synchronization-free prefill slot invalidation

Inspired by [issue #501](https://github.com/FlashML-org/FreeToken/issues/501),
we replaced CUDA boolean indexing in `_invalidate_prefill_buffer` with one
fixed-shape Triton kernel. It clears the same expert-to-slot mappings, slot IDs
and LRU usage values on the current stream. Valid resident expert IDs are unique
across slots, so mapping writes do not race. Existing copy/compute fences remain.

The old boolean gather calls `aten::nonzero` and needs its result shape on the
host, unnecessarily draining queued work. The new kernel removes that wait.
CPU behavior stays on the old path; `FREETOKEN_PREFILL_INVALIDATE_FUSED=0` is the
A/B fallback. Tests cover empty slots, both buffers, 8/257/512-expert geometries,
unaffected slots, repeated graph replay and the absence of data-dependent
`nonzero`. The profiler regression failed before this change and passed after.

## Correctness evidence and its limits

The audit suite exercises MTP bookkeeping, PLE, GDN, prefill hit-D2D and the new
invalidation kernel: **135 passed, 4 skipped** with one CPU BLAS thread. The four
skips require optional Hugging Face reference code or real-weight fixtures.

An existing CPU PLE snapshot test uses bit equality between matrix operations of
different batch shapes. With the default multi-thread CPU runtime, it failed
both on the untouched Kai implementation and on our candidate. With
`OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`, the full focused suite passes. The assertion
was not loosened or deleted. This test setting does not change the 12-worker
production MoE configuration. Logs are included, including the failure.

The earlier native extension build used CUDA toolkit 13.3. The audit adds Python
and Triton changes only; Triton compilation is exercised by the GPU tests and
warmup. A redundant C++ rebuild would not validate these new kernels.

Long-context retrieval, Vision, tool calls, Responses API, warm restart and
client-observed throughput are separately recorded. These checks do not replace
a full model quality benchmark or prove correctness for untested concurrency,
multi-GPU configurations, arbitrary image sizes or other model architectures.
