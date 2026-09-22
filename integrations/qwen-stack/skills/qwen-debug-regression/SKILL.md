---
name: qwen-debug-regression
description: "Diagnose reproducible bugs, failing tests and regressions using evidence and a regression test. Use before changing code for a reported failure."
---

# Diagnose before patching
1. Read repository instructions and the relevant code. Record the exact expected and observed behavior, failing command/input, environment, and first meaningful error. Separate pre-existing failures from the requested issue.
2. Find the smallest reproduction using the existing test framework. Read callers and boundaries; follow the actual data/control flow instead of changing the first suspicious line.
3. State one falsifiable hypothesis and the observation that would confirm it. Use a focused test or bounded diagnostic. If it fails, update the hypothesis; do not repeatedly retry unchanged work.
4. Patch the root cause with the smallest coherent change. Cover the original failure and a neighboring boundary: empty input, invalid input, concurrency/order, cancellation/cleanup, or compatibility as relevant.
5. Confirm the regression test fails on the old behavior when practical and passes after the change. Never weaken expectations to hide a defect. Preserve unrelated user changes.
6. Run affected checks, review the diff and report the reproduced cause, fix, evidence and any limitation. A passing toy test does not prove integration or deployment.

Use explicit command deadlines and preserve the check's exit status. Verify old
behavior in a disposable copy, without stashing/resetting the user's working tree.
Where available, inspect IDE/LSP diagnostics alongside the project checks.
