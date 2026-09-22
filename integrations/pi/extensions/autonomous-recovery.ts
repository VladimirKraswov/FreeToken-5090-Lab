import { existsSync } from "node:fs";
import { resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export const STATE_TYPE = "autonomous-recovery:v2";
export const COMPACT_AT_TOKENS = 60_000;
export const RECOVERY_PROMPT =
  "The previous response reached its output limit. Resume the assigned task once: " +
  "restore state from .pi/TASK.md and inspect Git status/diff before editing. " +
  "Call a tool within the first 300 words, make one small verifiable step, and keep reasoning brief. " +
  "Do not repeat truncated thinking. Stop if DONE or NEEDS_INPUT applies.";
const COMPACT_INSTRUCTIONS =
  "Preserve verified progress, blockers, Git state and the next concrete action. " +
  "Use .pi/TASK.md as the task checkpoint; discard repetitive or truncated reasoning.";

type Candidate = { triggerId: string; turnId: string; tokens: number; alreadyCompacted: boolean };
type Ticket = Candidate & { generation: number; finished: boolean };

function isTarget(ctx: ExtensionContext): boolean {
  return ctx.model?.provider === "local-qwen" && ctx.model.id === "qwen38-flash-next";
}

function textOf(message: any): string {
  if (typeof message?.content === "string") return message.content;
  return (message?.content ?? []).filter((part: any) => part.type === "text")
    .map((part: any) => part.text).join("\n");
}

export function hasTerminalText(message: unknown): boolean {
  return /^\s*(?:DONE|NEEDS_INPUT)(?:\s*:[^\n]*)?\s*$/m.test(textOf(message));
}

function terminalFile(cwd: string): boolean {
  return ["DONE", "NEEDS_INPUT"].some(name => existsSync(resolve(cwd, ".pi", name)));
}

function findCandidate(ctx: ExtensionContext): Candidate | undefined {
  const branch = ctx.sessionManager.getBranch();
  // Only the last conversational message may trigger recovery; never revive an old length stop.
  let index = branch.length - 1;
  while (index >= 0 && branch[index].type !== "message") index--;
  const entry = branch[index];
  if (!entry || entry.type !== "message" || entry.message.role !== "assistant") return;
  const message = entry.message;
  if (message.stopReason !== "length" || hasTerminalText(message)) return;
  if (message.provider !== ctx.model?.provider || message.model !== ctx.model?.id) return;

  // Budget belongs to the human task turn, not each truncated response. The recovery
  // message cannot rearm it. Persisted entries survive compaction, reload and resume.
  let turnId = `initial:${ctx.sessionManager.getSessionId()}`;
  for (let i = index - 1; i >= 0; i--) {
    const prior = branch[i];
    if (prior.type === "message" && prior.message.role === "user" && textOf(prior.message) !== RECOVERY_PROMPT) {
      turnId = prior.id;
      break;
    }
  }
  if (branch.some(item => item.type === "custom" && item.customType === STATE_TYPE &&
    (item.data as any)?.turnId === turnId)) return;

  const alreadyCompacted = branch.slice(index + 1).some(item => item.type === "compaction");
  const usage = ctx.getContextUsage();
  const measured = usage?.tokens;
  const fallback = [message.usage.input, message.usage.output, message.usage.cacheRead, message.usage.cacheWrite]
    .reduce((sum, n) => sum + (Number.isFinite(n) && n > 0 ? n : 0), 0);
  const tokens = alreadyCompacted ? 0 :
    (typeof measured === "number" && Number.isFinite(measured) ? measured : fallback);
  return { triggerId: entry.id, turnId, tokens, alreadyCompacted };
}

export default function autonomousRecovery(pi: ExtensionAPI) {
  let generation = 0;
  let closed = false;
  let pending: Ticket | undefined;
  let restoreThinking: ReturnType<ExtensionAPI["getThinkingLevel"]> | undefined;

  function record(ticket: Ticket, status: string, error?: string): void {
    pi.appendEntry(STATE_TYPE, {
      version: 2, turnId: ticket.turnId, triggerId: ticket.triggerId,
      status, tokens: ticket.tokens, ...(error ? { error } : {}),
    });
  }

  function finish(ticket: Ticket, ctx: ExtensionContext, status: string, error?: string): void {
    if (ticket.finished) return;
    ticket.finished = true;
    if (pending === ticket) pending = undefined;
    if (!closed) record(ticket, status, error);
    if (error && !closed) ctx.ui.notify(`Qwen recovery stopped: ${error}`, "warning");
  }

  function sendOnce(ticket: Ticket, ctx: ExtensionContext): void {
    if (ticket.finished) return;
    if (closed || generation !== ticket.generation || !isTarget(ctx) ||
        ctx.signal?.aborted || !ctx.isIdle() || ctx.hasPendingMessages() || terminalFile(ctx.cwd)) {
      finish(ticket, ctx, "cancelled");
      return;
    }
    const messages = ctx.sessionManager.getBranch().filter(item => item.type === "message");
    const last = messages.at(-1);
    if (!last || last.id !== ticket.triggerId || last.message.role !== "assistant" ||
        last.message.stopReason !== "length" || hasTerminalText(last.message)) {
      finish(ticket, ctx, "cancelled");
      return;
    }
    // Mark before dispatch: reentrant settled/callback events cannot enqueue a second turn.
    finish(ticket, ctx, "sent");
    restoreThinking = pi.getThinkingLevel();
    pi.setThinkingLevel("low");
    pi.sendUserMessage(RECOVERY_PROMPT, { deliverAs: "followUp" });
  }

  pi.on("session_start", (_event, ctx) => {
    closed = false; generation++; pending = undefined; restoreThinking = undefined;
    // Apply the quality profile on load; the single recovery uses Low temporarily.
    // Apply the requested Qwen worker profile once on startup/reload, not every turn.
    if (isTarget(ctx)) pi.setThinkingLevel("medium");
  });
  pi.on("model_select", (_event, ctx) => {
    restoreThinking = undefined;
    // Selecting Qwen should start with the quality profile.
    if (isTarget(ctx)) pi.setThinkingLevel("medium");
  });
  pi.on("session_shutdown", () => { closed = true; generation++; });
  pi.on("input", event => {
    // User steering or another extension supersedes a pending compaction callback.
    if (event.source !== "extension" || event.text !== RECOVERY_PROMPT) generation++;
  });
  pi.on("agent_end", (event, ctx) => {
    if (restoreThinking !== undefined) {
      if (isTarget(ctx) && pi.getThinkingLevel() === "low") pi.setThinkingLevel(restoreThinking);
      restoreThinking = undefined;
    }
    const last = [...event.messages].reverse().find(message => message.role === "assistant");
    if (last?.role === "assistant" && ["aborted", "error"].includes(last.stopReason)) generation++;
  });

  // Pi has now finished its own retries, compaction and queued follow-ups. At this
  // boundary we can compact safely and cannot race an ordinary queued user request.
  pi.on("agent_settled", (_event, ctx) => {
    if (closed || pending || !isTarget(ctx) || !ctx.isIdle() ||
        ctx.hasPendingMessages() || ctx.signal?.aborted || terminalFile(ctx.cwd)) return;
    const candidate = findCandidate(ctx);
    if (!candidate) return;
    const ticket: Ticket = { ...candidate, generation, finished: false };
    // Reserve synchronously, before any asynchronous operation; failure consumes the
    // one-shot budget too. No project files, retry timers or process restarts are used.
    record(ticket, "reserved");
    pending = ticket;
    if (ticket.tokens < COMPACT_AT_TOKENS || ticket.alreadyCompacted) {
      sendOnce(ticket, ctx);
      return;
    }
    try {
      ctx.compact({
        customInstructions: COMPACT_INSTRUCTIONS,
        onComplete: () => sendOnce(ticket, ctx),
        onError: error => finish(ticket, ctx, "compaction_failed", error.message),
      });
    } catch (error) {
      finish(ticket, ctx, "compaction_failed", error instanceof Error ? error.message : String(error));
    }
  });
}
