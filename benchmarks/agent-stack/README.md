# Local coding-agent acceptance evaluation

This is a small engineering acceptance suite for one deployed model, not an
estimate of SWE-bench performance or of parity with proprietary frontier models.
All agent runs use the same local `qwen38-flash-next` endpoint, NVFP4 checkpoint,
Medium reasoning, 131072-token server context and a 16384-token response budget.
Sampling is temperature 1 / top-p 0.95 / top-k 20. Runs are sequential.

Two dependency-free, freshly created Git repositories exercise:

1. Python async cache: coalescing, cancelled waiters, TTL, exceptions, generations.
2. JavaScript editor history: pointer ownership, cancellation, redo and isolation.

Each agent sees the same contract, faulty implementation and public baseline test.
It can add tests but must preserve the existing tests and an uncommitted user note.
Eight acceptance tests per task live outside the candidate repository. Their
contents are not included in the prompt. They are held-out checks, **not a security
sandbox**: the agents are explicitly instructed to stay inside their test repo.
No real user project is an evaluation target.

The baseline uses each agent's native core tools with the same coding guardrails.
Pi uses its SDK; OpenCode its native build agent; Qwen Code its CLI; DeepSeek
Harness its native headless profile. Their system prompts and tool schemas differ
by design. Do not present these runs as an isolated comparison of the model itself.

The audit proxy records only request metadata, tool names, timing and token usage.
It does not rewrite inference parameters. Candidate transcripts remain local;
publish only sanitized metrics and synthetic fixture artifacts. Fixture output
tokens include thinking. Summed input tokens count replayed/cached tokens too.

Limits: 10 minutes per trial (630-second outer process timeout), 32 model turns
where the client supports this bound, 15 seconds for the dependency-free public
suite during final grading and 20 seconds for held-out checks. Timeout/unfinished
turns are recorded as failures, including when implementation-only checks pass.
Native shell timeout differences are part of the baseline's operational behavior.
Any targeted rerun after a harness fix is labeled separately, never substituted
for the original result. A single stochastic run is not a statistical ranking.

## Reproduce

Inspect `run.py` and adapt tool locations and endpoint to your own installation.
Pinned candidates: Pi 0.85.1, DeepSeek Harness 0.1.1-rc.2, OpenCode 1.18.18,
Qwen Code 0.24.3. Node 26.7.0; Python 3.14.6. Dependencies belong to the harness,
not the fixture projects.

Start `node audit-proxy.mjs` with `UPSTREAM=http://your-freetoken-host:1919`, then
run `python3 run.py <pi|opencode|dsh|qwen> <cache|history>` one at a time.
`fixtures.py` refuses to overwrite existing runs. `run.py --grade-only` rechecks
an existing run without prompting the model. Raw results live in `results/`.

## Why these candidates

- [Qwen's model card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) reports
  evaluations with both Claude Code and mini-SWE-agent. Harness choice matters;
  this does not establish a winner on a local quantized deployment.
- [Qwen Code](https://github.com/QwenLM/qwen-code) explicitly supports local
  OpenAI-compatible models, native tools and IDE/terminal interfaces.
- [OpenCode](https://opencode.ai/docs/providers/) supports a custom local provider.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) exposes
  model adapters, context management and tool presentation separately.
- Claude Code was reviewed but not made the primary candidate: its
  [gateway documentation](https://code.claude.com/docs/en/llm-gateway) states that
  routing to non-Claude models is not officially supported. Existing cloud
  authentication/settings are preserved.
- mini-SWE-agent remains a useful batch-repair research baseline, but was not
  installed or timed here. No performance claim about it follows from this suite.

For portable runs set `UPSTREAM` to the actual engine URL without `/v1` and
`DSH_ROOT` to the installed `@deepseek-ai/dsh` package directory. Set `PI_SDK_URL`
to the Pi SDK entry module if it is not resolvable normally. Install Qwen Code
0.24.3 under `qwen-runtime` (`npm install --prefix qwen-runtime
@qwen-code/qwen-code@0.24.3`). The runner reads only the configured local provider
from each existing agent catalog; review those mappings before running it.
Pi and Qwen Code have a 600-second native deadline; the shared outer process
cap is 630 seconds. DSH/OpenCode use that outer cap. Timings include these native
tool/runner differences. The DSH cache trial finished at 625 seconds: successful
checks, but over a strict 600-second budget.

Recorded [metrics](data/summary.csv), [wire metadata](data/requests.json),
[acceptance logs](data/checks/) and [candidate patches](data/patches/) contain only
synthetic fixture artifacts. Raw session transcripts stay private. To replay a
patch, create the corresponding fresh fixture with `fixtures.py`, apply the patch
with `git apply`, then run the acceptance script with `CANDIDATE=<fixture>`.
The production-profile validation has an explicit exception allowing its two
installed read-only skill/inspection tools; it is not a second baseline trial.
