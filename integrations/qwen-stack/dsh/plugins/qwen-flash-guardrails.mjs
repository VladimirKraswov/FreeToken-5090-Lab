import {isFlashNext, loadGuardrails} from '../../.pi/agent/operations/qwen-guardrails/runtime.mjs';

export const name = 'qwen-flash-guardrails';
export const inject = ['systemPrompt'];
export function apply(ctx) {
  ctx.on('system-prompt/assemble', async (_assembly, _context, next) => {
    const result = await next();
    if (!isFlashNext(result.variables.model)) return result;
    // Substitution values are not rescanned by Harness' strict template engine.
    return {...result,
      sections: [...result.sections.filter(s => s.name !== name),
        {name, order: 10, text: '{{qwen_flash_guardrails_content}}'}],
      variables: {...result.variables, qwen_flash_guardrails_content: loadGuardrails()},
    };
  });
}
