import {isFlashNext, loadGuardrails, stripGuardrails} from '../../../.pi/agent/operations/qwen-guardrails/runtime.mjs';

export const QwenFlashGuardrails = async () => ({
  'experimental.chat.system.transform': async ({model}, output) => {
    // OpenCode retains this array reference; replacing output.system is ignored.
    output.system.splice(0, output.system.length, ...output.system.map(stripGuardrails).filter(Boolean));
    if (isFlashNext(model?.id) || isFlashNext(model?.api?.id)) {
      // Qwen accepts one leading system message. A second array item is serialized
      // as another system message by this OpenCode provider and fails the template.
      const combined = [...output.system, loadGuardrails()].join('\n\n');
      output.system.splice(0, output.system.length, combined);
    }
  },
});
