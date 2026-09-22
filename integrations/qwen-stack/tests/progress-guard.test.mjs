import test from 'node:test';
import assert from 'node:assert/strict';
import {ProgressGuard} from '../opencode/plugins/progress-guard.js';

test('read-only review can complete more than eight Git inspections without Todo',async()=>{
 const hooks=await ProgressGuard();let reminders=0;
 for(let i=0;i<17;i++){
  const input={sessionID:'readonly-review-test',tool:'bash'};
  await hooks['tool.execute.before'](input,{args:{command:'git diff --stat'}});
  const out={output:'diff evidence'};await hooks['tool.execute.after'](input,out);
  if(out.output.includes('[Progress reminder]'))reminders++;
  assert.ok(out.output.startsWith('diff evidence'));
 }
 assert.equal(reminders,2);
});
test('Todo validation remains meaningful and valid updates reset reminders',async()=>{
 const hooks=await ProgressGuard(),input={sessionID:'todo-test',tool:'todowrite'};
 await assert.rejects(()=>hooks['tool.execute.before'](input,{args:{todos:[]}}),/пустым/);
 await hooks['tool.execute.before'](input,{args:{todos:[{status:'in_progress',content:'Verify'}]}});
});
