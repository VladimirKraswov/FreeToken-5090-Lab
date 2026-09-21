# Bounded autonomous worker contract

The TypeScript extension `autonomous-recovery.ts` is loaded by Pi CLI and
Pi Code GUI through the global resource loader. It applies to
`local-qwen/qwen38-flash-next`; no `.pi/AUTONOMOUS` marker is required.

- Use Low thinking for short, verifiable coding steps. Start recovery by reading
  `.pi/TASK.md` and inspecting Git status/diff. Call a tool within the first
  300 words; do not repeat the truncated reasoning or reconstruct the whole plan.
- Preserve existing work. After a verified increment, update the task checkpoint
  according to the project's own instructions. Never reset a working tree just
  because a response was truncated.
- Recovery is limited to **one automatic follow-up per human task turn**, and
  only after `stopReason=length`. A second truncated recovery stays stopped.
  A fresh human instruction may start a new one-shot budget.
- When recovery context usage is at least 60000 tokens, first compact; continue
  only after successful completion. If Pi already compacted after that response,
  do not compact again using stale pre-compaction usage.
- Do not continue after `aborted` or `error`, a queued user message, or terminal
  `DONE` / `NEEDS_INPUT` state. These markers may be `.pi/DONE` and
  `.pi/NEEDS_INPUT` files or standalone final text lines. Merely mentioning a
  filename or marker in reasoning is not a terminal declaration.
- A compaction failure consumes the recovery budget and stops. No retry timers,
  unconditional process restarts, or extension-created project marker files.
- Complete the acceptance criteria assigned by the user. If completion or a
  necessary user decision is reached, report DONE or NEEDS_INPUT explicitly.
- Keep output focused on evidence, changed files and remaining work.

The recovery instruction is a model instruction, not a guarantee that any
arbitrary model response will obey the 300-word tool requirement. The hard
safety bound is one automatic continuation; a model that exhausts it waits for
new human input.
