---
name: qwen-browser-check
description: "Validate a local web UI in a real isolated browser: interaction, console errors, screenshots and responsive layout. Use after user-facing UI changes."
---

# Browser validation for local UI changes
Use the agent's native browser tool when available. Otherwise the installed `agent-browser` CLI is available through the native shell tool.
Before invoking it, read its version-matched guide with `agent-browser skills get core --full`; use that documentation for exact syntax rather than guessing commands.
1. Start the project's documented development/test server; confirm its loopback URL is ready. Keep it attached to a managed job where supported.
2. Use a unique browser session for this task. Open the local URL, take an interactive snapshot, and use fresh element references after navigation or a rerender.
3. Exercise the actual acceptance flow, one relevant error/empty state, and keyboard/form behavior where changed. Check console errors and failed network requests.
4. Inspect a screenshot at desktop and narrow/mobile dimensions for overlap, clipping and readability. A screenshot alone does not validate interactions.
5. Re-run the affected flow after fixes. Save concise evidence when useful, close only the browser session you created, and stop only the development server you started.
Never attach to the user's personal browser profile, reuse their cookies, perform unrelated external actions, or close all browser sessions as part of a local smoke test.
