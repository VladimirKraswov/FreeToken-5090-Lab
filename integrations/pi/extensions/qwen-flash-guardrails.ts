import type {ExtensionAPI} from '@earendil-works/pi-coding-agent';
import {isFlashNext, loadGuardrails, stripGuardrails} from '../operations/qwen-guardrails/runtime.mjs';

export default function(pi: ExtensionAPI) {
  pi.on('before_agent_start', (event, ctx) => {
    const base = stripGuardrails(event.systemPrompt);
    return {systemPrompt: isFlashNext(ctx.model?.id) ? `${base}\n\n${loadGuardrails()}` : base};
  });
  // Refresh every serialized request too: tool steps and post-compaction calls.
  pi.on('before_provider_request', (event, ctx) => {
    const payload = event.payload as any;
    if (!isFlashNext(payload?.model) || !Array.isArray(payload.messages)) return;
    try {
      const block = loadGuardrails();
      const messages = payload.messages.map((m: any) =>
        (m.role === 'system' || m.role === 'developer') && typeof m.content === 'string'
          ? {...m, content: stripGuardrails(m.content)} : m);
      const index = messages.findIndex((m: any) => m.role === 'system' || m.role === 'developer');
      if (index < 0) messages.unshift({role: 'system', content: block});
      else messages[index] = {...messages[index], content: `${messages[index].content}\n\n${block}`};
      return {...payload, messages};
    } catch (error) {
      // Pi reports hook errors but otherwise proceeds: cancel the request explicitly.
      void ctx.abort();
      throw error;
    }
  });
}
