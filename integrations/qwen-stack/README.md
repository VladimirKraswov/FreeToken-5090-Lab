# Shared Qwen coding configuration

Target: `qwen38-flash-next`, FreeToken, 131072 context, 16384 response tokens,
Medium, temperature 1, top-p .95, top-k 20. One active GPU request at a time.
See the [measured comparison](../../docs/rtx5090/AGENT_STACK.md), including failures.

These are **merge examples**, not replacements for private configuration. Back up
existing files. Keep other providers, credentials, sessions and working projects.
The shared source of behavioral guidance is installed by the [Pi integration](../pi/)
at `~/.pi/agent/operations/QWEN_FLASH_NEXT_GUARDRAILS.md`; it is not copied into
every conversation as a growing log. Each supported hook refreshes it per request.

## OpenCode 1.18.18

Merge `opencode/opencode.merge.json` into `~/.config/opencode/opencode.jsonc` and
set the real endpoint, including `/v1`. Copy the `agents`, `plugins`, `tools` and
`instructions` subdirectories into that config directory. Preserve other plugins.
The two plugin imports expect the shared Pi runtime at its default location.
Copy the three `skills` subdirectories to `~/.config/opencode/skills/`.
Use `qwen-build` / Medium; `qwen-review` is a read-only optional sequential reviewer.
Native LSP, Git diff/snapshots, shell/tests, repository inspection and browser CLI
validation cover the actual coding workflow. No paid/cloud fallback is configured.
The progress reminder must never block a tool or require a read-only reviewer to
write a Todo. Existing Todo validation still applies when a plan is actually used.

Run `opencode debug agent qwen-build` and `opencode debug skill` to check loaded
resources, then start `opencode` in a project or `opencode web --hostname 127.0.0.1`.
These files match the pinned v1 release; do not mix them blindly with v2 schemas.

## Pi CLI / Pi Code GUI

Install the [Pi integration](../pi/) and copy `skills/*` into `~/.pi/agent/skills/`.
Use TypeScript Pi 0.85.1 and Pi Code GUI 0.2.3. The GUI can additionally expose
VS Code diagnostics; CLI sessions use the project's actual test/typecheck commands.
Existing Pi browser and web tools remain available. Reload an idle GUI session's
context files (or start a new session) to activate updated extensions.

## DeepSeek Harness 0.1.1-rc.2

Copy `dsh/plugins/qwen-flash-guardrails.mjs` into `~/.dsh/plugins/` and the skills
into `~/.dsh/skills/`. Keep the configured local pi-ai provider, its explicit Medium
reasoning and the existing context-handoff/preflight plugins. The latter preserve
the original transcript when switching from a larger-context model; this package
does not replace or delete sessions. This hook uses the same shared Pi runtime.
Restart only an idle Harness instance when activating changed plugin code.

## What the skills do

- `qwen-debug-regression`: reproduce, test a hypothesis, fix the root cause.
- `qwen-verify-change`: discover real project checks, verify acceptance and review.
- `qwen-browser-check`: exercise user-visible behavior in an isolated browser.

The repository inspection helper is read-only and does not install dependencies
or execute project scripts. Browser validation uses the separately installed
`agent-browser` CLI or the agent's native browser tool; read its versioned guide.
Adding many unrelated tools or large always-loaded prompts is not evidence of
better code. Skills are loaded when relevant. The concise guardrails contain the
cross-task rules; task state belongs in the project's compact checkpoint.
