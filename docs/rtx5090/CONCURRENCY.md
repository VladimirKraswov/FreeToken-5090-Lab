# Concurrent sessions on one RTX 5090

This configuration targets Qwen3.8-Flash-Next-NVFP4 on the single-GPU,
CPU-offload setup described in [hardware.md](hardware.md) and
[reproduce.md](reproduce.md). Scheduling, CUDA-graph coverage and admission
are separate controls. Raising the active-request limit alone does not bound
streaming pauses or allocate an independent context pool to each session.

## Configuration

The scheduler default remains `prefill-first`. A controlled three-stream
trial can use the existing launcher's trailing overrides:

```bash
bash deploy/rtx5090/serve.sh \
  --max-running-requests 3 --cuda-graph-max-bs 4 \
  --scheduler-policy fair \
  --scheduler-decode-burst-ms 200 \
  --scheduler-decode-burst-steps 8
```

Set `MODEL_DIR` and the existing deployment environment as in
[reproduce.md](reproduce.md). These are experiment settings, not a claim that
the deployed service uses them. For a matched scheduling control, retain all
other options and select `--scheduler-policy prefill-first`. Compare a
four-stream limit separately; it changes the state-pool and expert-cache
budgets even when only one request is running.

Keep the checkpoint, NVFP4 experts, BF16 KV, FP32 recurrent state, MTP depth,
context/KV reserve, host placement and sampling settings fixed when comparing
schedulers. The launcher already enables `--moe-prefill-hit-d2d`.

## Scheduling and graph coverage

With both kinds of work available, `fair` runs one prompt-prefill batch,
then generation batches until either 200 ms of completed service or eight
generation batches have accumulated. Both limits are configurable. One MTP
verification counts as a generation batch, regardless of accepted tokens.
Service time includes scheduling/preparation, the forward and result draining.
The budget is checked after completion, so one slow generation batch can
exceed it. If one kind of work cannot run, the other can proceed.

The policy uses the non-overlapped scheduler loop so that decisions follow
completed work. `--tp-size > 1` and `--pp-size > 1` reject `fair` at startup.
MTP already requires this non-overlapped loop. Its existing verification path
still applies only with one active decoding request; two or more use ordinary
batched decode. This change does not implement batched MTP.

An executing prefill batch cannot be interrupted. `--max-prefill-length` and
the resolved `--prefill-chunk-budget` therefore still determine how long one
prefill can hold the GPU. Smaller chunks may shorten one pause while increasing
expert-bank transfers per prompt. The burst budget is not a maximum SSE gap,
and the policy does not provide per-user priorities or a queue deadline.

The graph-size resolver now includes the exact positive configured ceiling:

| Graph ceiling | Captured sizes | Three-request decode |
|---|---|---|
| 2 | `[1, 2]` | eager |
| 3 | `[1, 2, 3]` | graph 3 |
| 4 | `[1, 2, 4]` | graph 4, padded by one dummy row |

Without an override, the engine normally uses `max_running_requests` as the
ceiling. Previously a ceiling of 3 omitted graph 3. An explicit ceiling below
the active batch size still permits eager decode. Explicit internal graph-size
lists and `--disable-cuda-graph` retain their meanings. Verify the startup
`Start capturing CUDA graphs with sizes:` line for the actual configuration.
Graph 4 does not admit a fourth request when the active limit is 3.

## Admission and memory

The 262144-token KV pool is shared by active sequences and retained prefixes.
Admission charges whole pages for the prompt plus `max_tokens`, subtracts a
reusable prefix, locks that prefix, and rechecks capacity. It also reserves
remaining output for running requests and checks request/GDN slots. Shared
prefix pages are counted once; they still consume pool capacity while locked.
Four independent 65536-token prompts cannot fit together with positive output.

For an ordinary full-token page pool, a fresh request whose page-rounded
prompt plus output exceeds the entire pool now receives a terminal
`context_length_exceeded` error. Rejection happens before allocation or disk
restore, removes only that impossible request, and preserves the order of
remaining requests and continuations. Temporary resource pressure still queues.
The conservative check excludes SWA/tiered and unknown cache variants, which
retain their existing checks. The existing context-length check and output
clamp at the scheduler's message boundary are unchanged.

Offline `LLM.generate` records terminal errors by request, finishes the other
requests, then raises `ValueError` with the failed request IDs and messages.
This keeps the allocator reusable for a later `generate` call; successful
partial outputs are not returned from a failed batch.

Hybrid GDN usable device slots are allocated at startup as:

```text
4 * max_running_requests + max(4, int(linear_state_cache_ratio * max_running_requests))
```

There is one additional physical padding slot. The four working slots cover
live state, two prefill tracking slots and a committed snapshot. At limits
1/3/4, the default ratio 2 reserves 8/18/24 usable slots; ratio 1 gives
8/16/20. Ratio 0 gives the same counts as ratio 1 at these limits.

On this model's recorded geometry, one slot is 115642376 bytes. Testing
`--linear-state-cache-ratio 1` at C=3 therefore releases about 231 MB relative
to ratio 2, equivalent to about 83 expert-cache slots under an unchanged
budget. This is memory arithmetic, not a throughput measurement.

`--linear-state-host-slots 8` is a separate optional prefix-reuse experiment,
costing about 925 MB of pinned host RAM at that geometry. It preserves unlocked
snapshots under device pressure; it does not swap active recurrent state or
add KV capacity. Copies compete with expert offload for host/PCIe resources.
Neither memory option is implied by `--scheduler-policy fair` or prescribed
as deployed here. See [prefix-reuse.md](../prefix-reuse.md).

Runtime GDN/KV resizing requires an idle scheduler, invalidates retained
prefixes and recaptures CUDA graphs. It is unsuitable as a per-request mode
switch. Free slots inside an allocated state pool do not automatically become
expert-cache memory.

## Validation

In an existing development environment, the CPU gate can run with CUDA hidden:

```bash
CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=python \
  uv run python -m pytest -q tests/scheduler \
  tests/engine/test_scheduler_policy_args.py tests/moe/test_offload.py
```

This covers scheduling decisions, completion-based budgets, argument rejection,
admission errors, temporary pressure, shared prefixes, chunk continuations,
abort/resource handling and graph-size resolution. CPU tests do not validate
GPU replay, model output quality or serving throughput.

For each full-model profile, finish warmup and exclude unrelated requests,
tests and builds. Record the exact revision, command, graph sizes, resolved
prefill chunk and KV/GDN/expert geometry. Run at least three paired repetitions
of C=1/2/3, then C=4 separately, using identical input/output budgets. Include:

- Short and long coding prompts, with fixed-length throughput and naturally
  stopping correctness cases reported separately.
- An established stream followed by a new long prefill; report TTFT, per-stream
  SSE gap percentiles/maximum, whole-wave latency and aggregate tokens/s.
- Repeated conversation switching and shared prefixes, plus cold unique
  prompts that prevent accidental cache reuse.
- Tool calls, reasoning output, bounded tails, cancellation during prefill and
  generation, and return from multiple active requests to C=1 MTP.

Compare policy first with memory geometry fixed. Test ratio 1 and any host
snapshot tier separately. Select a production profile only from measured
latency, throughput and correctness results; retain the previous service
configuration for rollback after active work drains.
