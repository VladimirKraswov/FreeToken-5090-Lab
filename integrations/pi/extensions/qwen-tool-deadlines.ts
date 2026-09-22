import type {ExtensionAPI} from '@earendil-works/pi-coding-agent';
import {isFlashNext} from '../operations/qwen-guardrails/runtime.mjs';

export function installDeadlines(pi: ExtensionAPI, seconds = 120) {
  if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('Invalid default tool deadline');
  pi.on('tool_call', (event, ctx) => {
    if (!isFlashNext(ctx.model?.id) || event.toolName !== 'bash') return;
    const args = event.input as {timeout?: number};
    // Pi's native bash tool kills its own process tree and reports a tool error.
    // An explicit longer build/download deadline remains the agent's choice.
    if (args.timeout === undefined) args.timeout = seconds;
  });
  pi.on('before_agent_start', (event, ctx) => {
    if (!isFlashNext(ctx.model?.id)) return;
    return {systemPrompt: event.systemPrompt + '\nForeground bash calls default to a 120-second timeout. Specify a longer timeout explicitly for known long builds, downloads or stateful operations; manage persistent servers as background jobs. A timed-out check is a failure to diagnose, never a pass. Preserve the real exit status of checks; do not mask it with a pipe to tail.'};
  });
}

export default function(pi: ExtensionAPI) { installDeadlines(pi); }
