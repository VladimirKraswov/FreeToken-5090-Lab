import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

export const SOURCE = fileURLToPath(new URL('../QWEN_FLASH_NEXT_GUARDRAILS.md', import.meta.url));
export const BEGIN = '<qwen_flash_next_guardrails>';
export const END = '</qwen_flash_next_guardrails>';
export function isFlashNext(id) {
  return typeof id === 'string' && id.split('/').at(-1).toLowerCase()
    .replace(/[._-]/g, '').replace(/nvfp4$/, '') === 'qwen38flashnext';
}
export function loadGuardrails(path = SOURCE) {
  const body = readFileSync(path, 'utf8').trim();
  if (!body || Buffer.byteLength(body) > 12288) {
    throw new Error(`Qwen guardrails must be nonempty and at most 12 KiB: ${path}`);
  }
  if (body.includes(BEGIN) || body.includes(END)) throw new Error('Reserved guardrails delimiter in source file');
  return `${BEGIN}\nSource: ${path}\nApply this current guidance before acting on this task.\n${body}\n${END}`;
}
export function stripGuardrails(text) {
  return text.replace(/\n*<qwen_flash_next_guardrails>[\s\S]*?<\/qwen_flash_next_guardrails>/g, '').trimEnd();
}
