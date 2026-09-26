# Preserve the agent's reasoning effort

The local agent comparison exposed a protocol integration defect, separate from
the [missing tool-call boundary](QWEN_TOOL_HANDOFF.md) fixed earlier.

OpenCode sent the following combination for its Medium profile:

```json
{
  "model": "qwen38-flash-next",
  "reasoning_effort": "medium",
  "chat_template_kwargs": {
    "enable_thinking": true,
    "preserve_thinking": true
  }
}
```

`effort_toggle_kwargs` previously returned the entire template-kwargs dictionary
unchanged as soon as it found any thinking-related key. The explicit enabled
toggle therefore discarded the separate Medium effort. Qwen's checkpoint
template defaults to **xhigh** when `reasoning_effort` is absent. The UI and the
rendered model prompt could disagree despite a correctly formed client request.

The helper now allows an explicit enabled toggle to inherit a positive protocol
effort when no template effort is present. Explicit template effort, disabled
thinking and adaptive mode retain their precedence. Unknown controls are not
rewritten, and the caller's dictionary is not mutated. No weights, kernels,
context limits, sampling defaults or MTP acceptance rules changed.

## Validation

- The two minimal regression cases failed against deployed commit `d57d880`.
- The final full server suite plus those two cases passed: **668 tests**
  (28.57 seconds; two dependency deprecation warnings). The enabled/adaptive
  edge case, explicit-off behavior and the older protocol tests remain covered.
- The real checkpoint tokenizer was rendered locally for Low, Medium and xhigh.
  Medium no longer contained the xhigh instruction; Low and xhigh still contained
  their respective native instructions.
- Agent-comparison OpenCode trials used an explicit template Medium during the
  comparison, so they did not benchmark the accidental xhigh configuration.

Medium is a model instruction, not a hard reasoning-token quota. This fix cannot
guarantee a short thought or correct code. A shell command waiting forever also
belongs to the agent runner, not to GPU inference: use bounded foreground tools,
preserve exit codes and diagnose timeouts instead of reporting successful tests.

At the time of this fix the serving window remained 131072, with Vision and
MTP=3. The later context change is documented in
[context-tuning-20260927.md](context-tuning-20260927.md). This fix was about
honoring the selected profile; it was not a new tokens-per-second claim.

A targeted search of upstream and Kai issues for `reasoning_effort
chat_template_kwargs` and `Qwen tool thinking` found no exact matching report on
2026-09-22. This is a narrow search, not proof that no related work exists.
