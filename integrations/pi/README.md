# Qwen Pi integration — updated 2026-09-22

Status: implemented and tested for Pi 0.85.1 and the TypeScript runtime of
Pi Code GUI 0.2.3. Existing working projects and session JSONL files were not
edited or deleted. Tests use disposable temporary Git repositories and
in-memory SDK sessions.

## Confirmed incident

A recorded session successfully compacted at tokensBefore=82324.
The next assistant message then ended with stopReason=length: input 24785,
output 32768, and one thinking block of 110943 characters. It contains no tool
call. This is response-output exhaustion, not a context overflow or timeout.
The report deliberately does not reproduce the model's private reasoning.

The old extension required `.pi/AUTONOMOUS`; that file was absent in the
reported project. `extensions=[]` alone does **not** disable Pi's global
extension auto-discovery. Pi Code GUI uses `DefaultResourceLoader` and
`bindExtensions`, so no GUI binary modification is needed. Explicit global
registration was added and tested to load once alongside auto-discovery.

The old recovery also continued normal stops, retried terminal errors, and had
no durable per-turn guard. The wrapper's unconditional restart loop could
bypass a stopped agent. Those behaviors were removed.

## Selected profile and documentation

- Qwen Flash Next: **Medium** for ordinary work; maxTokens=16384; context 131072.
- The one permitted length recovery temporarily uses **Low**, then restores the
  previous effort. Startup and model selection apply Medium, including resumed
  sessions; a user can deliberately select another level afterward.
- The current guardrails file is injected once on every serialized Qwen request,
  including tool steps and continuations after compaction.
- Foreground Pi bash calls default to 120 seconds for this model. Explicit
  longer deadlines remain available for builds/downloads. A timeout is a failure
  to diagnose, never a passed test. Other models are not changed.
- Pi Code GUI uses the same global TypeScript resources as the CLI.

[Pi's model configuration documentation](https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/docs/models.md#model-configuration)
lists 16384 as the **default** maxTokens for custom models. It is not a
Qwen-specific quality optimum. Medium follows the ordinary coding profile; Low
is a bounded recovery choice, not a claim that Qwen mandates it.

[The Qwen model card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next#best-practices)
supports low/medium/xhigh. Its very large separate reasoning/answer budgets are
described for a 1M-context configuration; they cannot be copied directly into
this 131K total-context server. Lowering the response cap alone cannot cure
reasoning-only exhaustion; bounded recovery is the accompanying control.

## Recovery contract

Only `local-qwen/qwen38-flash-next` is eligible. No project opt-in marker is
required. The extension waits for `agent_settled`, after Pi's own queued work
and built-in recovery finish, and then evaluates the latest assistant message.

1. Only a `length` stop can trigger one short continuation at Low effort, restoring
   the previous effort when it settles. It instructs the
   model to read `.pi/TASK.md`, inspect Git status/diff, and use a tool within
   the first 300 words. Normal stop/toolUse/error/aborted do not trigger it.
2. At usage>=60000, compact first and continue only on success. Cache-read and
   cache-write tokens are counted in the fallback usage estimate. A completed
   built-in compaction is detected so stale usage cannot trigger another one.
3. A durable `autonomous-recovery:v2` custom entry reserves the one-shot budget
   **before** compaction or dispatch. The guard is per human task turn and
   survives reload/resume/compaction. The recovery prompt never resets it.
4. A second length stop remains stopped. A new human instruction permits a
   new one-shot budget. Existing queued messages suppress automatic recovery.
5. `.pi/DONE`, `.pi/NEEDS_INPUT`, or standalone final text lines DONE / NEEDS_INPUT
   stop recovery. New input, terminal errors, shutdown, or a terminal marker
   during compaction cancel its delayed continuation.
6. Compaction failure consumes the budget and reports a warning. No retry
   timers, process restart loop, shutdown request, or project marker writes.

The 300-word rule is an instruction to the model, not a hard token-stream
cutoff. The hard bound is one automatic follow-up. Do not claim that every
possible prompt is now guaranteed to finish autonomously.

## Validation

The current portable suite has **39 Node tests and 3 Python tests**. It covers
event/state regressions, the real Pi SDK
against a scripted OpenAI endpoint, combined guardrails/recovery hooks, native
bash timeout behavior and wrapper exit codes. It checks Medium on ordinary
requests, Low only during recovery, restoration to Medium, no duplicate guardrail
injection, `length -> tools`, `compact -> continue`, and `length -> length -> stop`.
See `evidence/portable-tests.txt` for the exact current count.

The historical 2026-09-21 read-only endpoint test passed: Low,
maxTokens 16384, one tool call after 12 words (including thinking), checkpoint
and Git inspection, final READY with stopReason=stop. Elapsed 28.2s includes
request/queue overhead and is not a throughput benchmark.

```sh
cd integrations/pi
npm ci --ignore-scripts
npm test
python3 -m unittest discover -s tests -p "test_*.py"
```

See [evidence/](evidence/) for the recorded local test log, live smoke result
and sanitized incident metadata. Source hashes in the manifest protect the current published artifacts.
The guardrail runtime resolves its source relative to its own installation.
The portable test copies resolve the pinned SDK dependency without machine paths.

## Activation in VS Code

New TypeScript Pi sessions load the updated configuration and extension.
For an already open session, wait until its current work has stopped and run
**PiGui: Reload Context Files**. The installed command calls `session.reload()`
and reloads extensions as well. Alternatively, reload the VS Code window.

The reported original session was still executing tool calls during diagnosis;
it was not interrupted or forcibly reloaded. This is runtime activation, not a
request to discard or recreate its conversation. The Rust Pi runtime does not
load TypeScript extensions and is outside this change.

## Installation and configuration

Requirements: TypeScript Pi 0.85.1 (already installed), Pi Code GUI 0.2.3,
a reachable FreeToken endpoint, and zsh only if using the optional wrapper.
The published tests use Node 26 and the lockfile-pinned Pi SDK 0.85.1.
`npm ci --ignore-scripts` installs test dependencies inside this directory;
it does not update the user's global Pi installation.

From the repository root, first back up the relevant existing configuration:

```sh
agent_dir="$HOME/.pi/agent"
backup_dir="$agent_dir/operations/recovery-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
for relative in extensions/autonomous-recovery.ts bin/pi-local-autonomous operations/AUTONOMOUS_WORKER.md settings.json models.json; do
  if [ -f "$agent_dir/$relative" ]; then
    mkdir -p "$backup_dir/$(dirname "$relative")"
    cp -p "$agent_dir/$relative" "$backup_dir/$relative"
  fi
done

mkdir -p "$agent_dir/extensions" "$agent_dir/operations"
install -m644 integrations/pi/extensions/*.ts "$agent_dir/extensions/"
install -m644 integrations/pi/operations/*.md "$agent_dir/operations/"
mkdir -p "$agent_dir/operations/qwen-guardrails"
install -m644 integrations/pi/operations/qwen-guardrails/runtime.mjs "$agent_dir/operations/qwen-guardrails/"
```

Merge the following fragments into existing files, preserving other models,
extensions, settings and credentials. They are **merge examples**, not full
configuration replacements:

- [examples/models.merge.json](examples/models.merge.json) -> `~/.pi/agent/models.json`.
  Set the actual `baseUrl`, including `/v1`, and the endpoint's credential if required.
  `local` is a placeholder for an endpoint without authentication.
- [examples/settings.merge.json](examples/settings.merge.json) -> `~/.pi/agent/settings.json`.
  Append each extension path to the existing list once. Keep the provider/model
  IDs `local-qwen/qwen38-flash-next`, or deliberately adjust the extension's
  `isTarget` predicate if deploying a different alias.
- [examples/vscode-settings.merge.json](examples/vscode-settings.merge.json) -> VS Code
  User `settings.json`. Use the **TypeScript** Pi runtime. The model is discovered
  from the same global Pi catalog; it does not need a second GUI model registry.

The optional bounded CLI wrapper can be installed separately:

```sh
mkdir -p "$agent_dir/bin"
install -m755 integrations/pi/bin/pi-local-autonomous "$agent_dir/bin/"
if [ ! -e "$agent_dir/bin/pi-local" ]; then
  install -m755 integrations/pi/bin/pi-local "$agent_dir/bin/"
fi
```

The supplied `pi-local` checks only the selected provider/model with `/v1/models`,
then invokes `pi` from PATH. It does not probe an idle GPU or start inference.
Install `operations/qwen-stack-20260922/check_endpoint.py` at the matching path
under the agent directory when using this launcher. Existing custom launchers
are preserved. `pi-local-autonomous` makes one process invocation, preserves its
exit status and never restarts automatically. It explicitly loads recovery and guardrails without disabling other configured
extensions, skills or packages. Ordinary Pi Code GUI sessions use the same
global resources. The launcher clears inherited NODE_PATH to avoid unrelated
project modules affecting the agent runtime.

For a read-only check against a real inference server (not run by CI):

```sh
cd integrations/pi
FT_BASE=http://your-inference-host:1919/v1 npm run test:live
```

Set `FT_API_KEY` if needed. The live check creates a disposable Git repository;
its only tool can read that repository's task file and run Git status. It cannot
execute arbitrary model-supplied shell commands. `live-smoke.json` is ignored
by Git. The recorded 28.2s result is historical evidence, not a promised latency.

Rollback: restore only the backed-up files, then reload an idle session. Keep
session histories and working trees. No private config backups or transcripts
are distributed in this repository.
