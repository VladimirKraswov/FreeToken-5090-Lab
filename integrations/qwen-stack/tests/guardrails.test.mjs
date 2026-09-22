import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,copyFileSync,rmSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

test('Qwen guardrails preserve the array reference and serialize one leading system message',async t=>{
 const root=mkdtempSync(join(tmpdir(),'qwen-plugin-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
 const plugin=join(root,'.config/opencode/plugins/qwen-flash-guardrails.mjs');
 mkdirSync(join(root,'.config/opencode/plugins'),{recursive:true});mkdirSync(join(root,'.pi/agent/operations/qwen-guardrails'),{recursive:true});
 copyFileSync(new URL('../opencode/plugins/qwen-flash-guardrails.js',import.meta.url),plugin);
 copyFileSync(new URL('../../pi/operations/qwen-guardrails/runtime.mjs',import.meta.url),join(root,'.pi/agent/operations/qwen-guardrails/runtime.mjs'));
 const source=new URL('../../pi/operations/QWEN_FLASH_NEXT_GUARDRAILS.md',import.meta.url);
 copyFileSync(source,join(root,'.pi/agent/operations/QWEN_FLASH_NEXT_GUARDRAILS.md'));
 const {QwenFlashGuardrails}=await import(pathToFileURL(plugin));
 const hook=(await QwenFlashGuardrails())['experimental.chat.system.transform'];
 const system=['Native system instructions','User coding preferences'],output={system};
 await hook({model:{id:'qwen38-flash-next'}},output);
 await hook({model:{id:'qwen38-flash-next'}},output);
 assert.equal(output.system,system);assert.equal(system.length,1);
 assert.ok(system[0].startsWith('Native system instructions\n\nUser coding preferences'));
 assert.equal(system[0].split(readFileSync(source,'utf8').trim()).length-1,1);
 const other={system:['Other model system','Other preferences']};
 await hook({model:{id:'another-model'}},other);
 assert.deepEqual(other.system,['Other model system','Other preferences']);
});
