# Qwen tool handoff reliability

## Incident and root cause (2026-09-22)

Pi Code GUI stopped after a response containing a single thinking block. It was
not a timeout or context overflow: finish reason was `stop`, output was 1796
tokens, and total usage including cached input was 55151 tokens. Inspection of
the stored 7493-character block found a complete 203-character `bash` tool call
at its end, with no closing `</think>` before it.

Qwen emitted a malformed boundary, and FreeToken's generic `ThinkReasoningParser`
assumed that boundary was mandatory. The complete call was mislabeled as
`reasoning_content`, so Pi never received `tool_calls` and correctly ended its
agent loop. A prior Pi extension handles output exhaustion (`length`); that is a
different failure mode and could not repair this lost tool handoff.

Replaying the actual stored output through the old and new API layers confirmed
this diagnosis. No command from the recorded response was executed during replay.
Private session text and command arguments are not included in this repository.

## Engine change

The `qwen3` reasoning parser now has a conservative fallback, enabled only when
`qwen3_coder` parsing and tools are enabled for the request:

- Keep ordinary reasoning streaming. Hold a suspected tool block until the turn
  ends, so a later `</think>` can still identify a quoted example as reasoning.
- Recover only complete terminal XML/JSON tool blocks at a line boundary, outside
  Markdown fences, with valid arguments and names offered by the request.
- Reject trailing prose, incomplete markup, unknown tools and missing required
  top-level arguments. Do not use this fallback after `length` or an explicit
  matched stop string. `tool_choice=none` disables it.
- Limit additional evidence storage to 262144 characters. Beyond that limit,
  preserve the old interpretation rather than guessing or growing memory.
- Pass recovered calls into the existing function parser. The server does not
  execute tools, add user prompts, retry generation, or override client approvals.

The fix is in the shared generation layer used by OpenAI Chat Completions,
Responses and Anthropic Messages. Clients continue using their existing endpoint.
CUDA kernels, weights, quantization, MTP depth and context size are unchanged.
There is no extra model request and no CUDA recompilation is needed.

The fallback is intentionally conservative: it does not infer calls from prose or
repair arbitrary malformed output. An unquoted terminal example that is exactly
valid tool syntax is inherently ambiguous; the model must still follow its tool
protocol. This patch is not a guarantee of model correctness.

## Diagnostics that distinguish generation from useful work

`GET /v1/requests` now adds these optional fields to generation records:

- `finish_reason`
- `reasoning_chars`, `content_chars`, `tool_calls`
- `first_action_ms`: time to the first non-whitespace visible text or tool-call
  event, measured for streams separately from time to the first thinking token.

These are character counts, not invented reasoning-token estimates. The journal
records recovered missing-boundary calls and reasoning-only normal stops using
counts only, without logging the reasoning or command contents. Non-streaming
requests leave `first_action_ms` unset because their intermediate arrival times
are unavailable.

## Validation

- The new missing-closer regression failed on the original source in both
  streaming and non-streaming modes (`stop`, zero calls).
- Recorded-incident replay: both modes now return `tool_calls`, exactly one
  `bash` call, and identical parsed arguments. No tools were executed.
- Final full server suite: **653 tests passed**, including dedicated missing-closer
  tests for all three APIs, normal and streaming responses, JSON, multiple calls,
  quoted examples followed by a real call, marker splitting and bounded storage.
- Live Pi TypeScript SDK with the installed guardrails and Medium reasoning:
  one read-only test tool, 200 words before it, final `READY`, no errors (17.434 s
  total). The working project and original session were not changed.
- Post-restart validation: exact retrieval from **105077 input tokens** in
  42.383 s, Vision color recognition, tool calling and Responses all passed.
  Automatic warmup completed and the service is active with no automatic restarts.
- On the production Xeon VM, 100 parser runs per case with ~8K characters split
  into 7-character deltas took median 5.5-5.6 ms with recovery disabled and
  7.8-7.9 ms with recovery enabled. Added parsing work was ~2.3 ms for the whole
  response. This is a parser microbenchmark, not a claim of higher GPU tok/s.

Reproduce the public suite on the configured VM:

```sh
cd /opt/freetoken/src/kai
PYTHONPATH=python /opt/freetoken/venv/bin/python -m pytest tests/server/ -q
```

At the time of this 2026-09-22 fix, production used context 131072, MTP=3,
NVFP4 Triton, Vision and a 500 W RTX 5090 cap. Deployment and post-restart
checks are in `reports/qwen-tool-handoff-live.json`. The later serving-context
selection is in [context-tuning-20260927.md](context-tuning-20260927.md).

## Next quality work

Measure success per coding task, tool-call validity and first-action latency,
not just raw decode tokens/s. Maintain sanitized recorded-output regressions for
protocol failures. Any future reasoning-budget or sampling change should be
compared on the same coding tasks, with explicit checks for answer correctness,
tool arguments, cancellation and context retention. Blind server retries or
forced execution of text found in thinking can duplicate actions; they are not
part of this fix.
