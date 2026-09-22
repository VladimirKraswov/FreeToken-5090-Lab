import test from 'node:test';
import assert from 'node:assert/strict';
import {installDeadlines} from '../extensions/qwen-tool-deadlines.ts';
import {createBashTool} from '@earendil-works/pi-coding-agent';

function setup(seconds){const hooks={};installDeadlines({on:(key,fn)=>hooks[key]=fn},seconds);return hooks;}
const ctx={model:{id:'qwen38-flash-next'}};
test('Qwen gets a deadline; explicit long-running commands keep their timeout',()=>{
 const hooks=setup();const event={toolName:'bash',input:{command:'python3 -m unittest'}};
 hooks.tool_call(event,ctx);assert.equal(event.input.timeout,120);
 const explicit={toolName:'bash',input:{timeout:900}};hooks.tool_call(explicit,ctx);assert.equal(explicit.input.timeout,900);
 const other={toolName:'bash',input:{}};hooks.tool_call(other,{model:{id:'another-model'}});assert.equal(other.input.timeout,undefined);
 const read={toolName:'read',input:{}};hooks.tool_call(read,ctx);assert.equal(read.input.timeout,undefined);
});
test('a hung native bash returns a failure instead of holding the agent indefinitely',{timeout:10000},async()=>{
 const hooks=setup(.15);const event={toolName:'bash',input:{command:"node -e 'setInterval(() => {}, 1000)'"}};
 hooks.tool_call(event,ctx);const start=Date.now();
 await assert.rejects(()=>createBashTool(process.cwd()).execute('deadline-test',event.input,new AbortController().signal),/timed out|timeout/i);
 assert.ok(Date.now()-start<5000);
});
