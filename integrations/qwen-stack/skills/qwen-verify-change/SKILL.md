---
name: qwen-verify-change
description: "Discover a repository test/lint/typecheck workflow and verify a code change or perform a final review. Includes a read-only repository inspection helper."
---

# Verify against acceptance criteria
Use native repo_inspect if available; otherwise run `python3 scripts/repo_inspect.py --root <project-root>` relative to this skill directory. It only reads repository metadata; it never executes package scripts or installs dependencies.
1. Map each user acceptance criterion to observable evidence. Inspect discovered manifests and CI; choose existing test commands rather than inventing them.
2. Capture initial Git state and relevant baseline failures. Read the affected code and callers. Use the project's package manager and lockfile.
3. Add meaningful tests for new behavior/bugs, including error paths and boundaries. Avoid tests that merely repeat implementation internals. Keep independent acceptance checks unchanged.
4. Run the smallest useful affected test first, then required lint/typecheck/integration checks. A test process still running is not a pass. Record command, exit code and failures without dumping unbounded logs.
5. Review the final diff separately: fulfilled behavior, regression risk, error handling, cleanup, permissions, compatibility, and unnecessary changes. For each finding give a concrete failing scenario and file.
6. Fix material findings, rerun affected checks, and state remaining unverified behavior. Mark completion only after the required evidence; do not claim cloud-level model quality from one fixture.

Use explicit command deadlines and preserve the check's exit status. Verify old
behavior in a disposable copy, without stashing/resetting the user's working tree.
Where available, inspect IDE/LSP diagnostics alongside the project checks.
