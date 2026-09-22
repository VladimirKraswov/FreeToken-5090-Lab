import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import recovery, { RECOVERY_PROMPT, STATE_TYPE } from '../extensions/autonomous-recovery.ts';

const usage = (total = 57553) => ({input:total-32768, output:32768, cacheRead:0, cacheWrite:0, totalTokens:total});
function harness(t, {tokens=57553, stop='length', text='', entries}={}) {
  const cwd=mkdtempSync(join(tmpdir(),'pi-recovery-unit-'));
  t.after(()=>rmSync(cwd,{recursive:true,force:true}));
  const handlers=new Map(), sent=[], notices=[], branch=entries??[
    {type:'message',id:'human1',message:{role:'user',content:'Complete the task'}},
    {type:'message',id:'assistant1',message:{role:'assistant',provider:'local-qwen',model:'qwen38-flash-next',stopReason:stop,usage:usage(),content:text?[{type:'text',text}]:[{type:'thinking',thinking:'x'.repeat(110943)}]}}
  ];
  const state={compactCalls:0,compactOptions:null,pending:false,idle:true,signal:undefined,tokens,throwCompact:false,thinking:"medium"};
  const pi={getThinkingLevel:()=>state.thinking,setThinkingLevel:level=>{state.thinking=level;},on:(event,fn)=>handlers.set(event,fn),appendEntry:(customType,data)=>branch.push({type:'custom',id:`custom${branch.length}`,customType,data}),sendUserMessage:(content,options)=>sent.push({content,options})};
  const ctx={cwd,model:{provider:'local-qwen',id:'qwen38-flash-next'},sessionManager:{getBranch:()=>branch,getSessionId:()=> 'session1'},isIdle:()=>state.idle,hasPendingMessages:()=>state.pending,getContextUsage:()=>({tokens:state.tokens}),get signal(){return state.signal;},compact:options=>{state.compactCalls++;state.compactOptions=options;if(state.throwCompact)throw Error('failed');},ui:{notify:(...args)=>notices.push(args)}};
  function load(){handlers.clear();recovery(pi);}
  async function emit(event,data={}){return handlers.get(event)?.(data,ctx);}
  function appendAssistant(id,reason='length'){branch.push({type:'message',id,message:{role:'assistant',provider:'local-qwen',model:'qwen38-flash-next',stopReason:reason,usage:usage(),content:[]}});}
  load();
  return {cwd,branch,state,ctx,pi,sent,notices,load,emit,appendAssistant};
}

test('recorded thinking-only length -> exactly one short continuation, without AUTONOMOUS marker', async t=>{
  const h=harness(t);await h.emit('agent_settled');
  assert.equal(h.sent.length,1);assert.equal(h.state.compactCalls,0);
  assert.equal(h.sent[0].options.deliverAs,'followUp');
  assert.match(h.sent[0].content,/\.pi\/TASK\.md/);assert.match(h.sent[0].content,/Git/);
  assert.match(h.sent[0].content,/first 300 words/);assert.ok(h.sent[0].content.split(/\s+/).length<100);
});

test('usage >= 60000 -> compact -> continue, never before compaction finishes', async t=>{
  const h=harness(t,{tokens:60000});await h.emit('agent_settled');
  assert.equal(h.state.compactCalls,1);assert.equal(h.sent.length,0);
  h.state.compactOptions.onComplete({});assert.equal(h.sent.length,1);
  h.state.compactOptions.onComplete({});assert.equal(h.sent.length,1);
});

test('unknown context uses actual usage including cached input',async t=>{
 const h=harness(t,{tokens:null});h.branch[1].message.usage={input:10000,output:10000,cacheRead:45000,cacheWrite:0};
 await h.emit('agent_settled');assert.equal(h.state.compactCalls,1);assert.equal(h.sent.length,0);
});

test('already compacted by Pi -> no redundant compaction using stale usage',async t=>{
 const h=harness(t,{tokens:null});h.branch[1].message.usage=usage(82324);
 h.branch.push({type:'compaction',id:'compact1',tokensBefore:82324});
 await h.emit('agent_settled');assert.equal(h.state.compactCalls,0);assert.equal(h.sent.length,1);
});

test('duplicate settled events and reloaded extension cannot requeue',async t=>{
 const h=harness(t);await h.emit('agent_settled');await h.emit('agent_settled');
 h.load();await h.emit('session_start');await h.emit('agent_settled');assert.equal(h.sent.length,1);
 assert.ok(h.branch.some(x=>x.customType===STATE_TYPE&&x.data.status==='reserved'));
});

test('recovery length -> stop; human input starts a new bounded budget',async t=>{
 const h=harness(t);await h.emit('agent_settled');
 h.branch.push({type:'message',id:'auto1',message:{role:'user',content:RECOVERY_PROMPT}});h.appendAssistant('assistant2');
 await h.emit('agent_settled');h.load();await h.emit('agent_settled');assert.equal(h.sent.length,1);
 h.branch.push({type:'message',id:'human2',message:{role:'user',content:'A new instruction'}});h.appendAssistant('assistant3');
 await h.emit('agent_settled');assert.equal(h.sent.length,2);
});

for(const reason of ['stop','toolUse','aborted','error'])test(`${reason} -> no continuation or compaction`,async t=>{
 const h=harness(t,{stop:reason,tokens:100000});await h.emit('agent_end',{messages:[h.branch[1].message]});await h.emit('agent_settled');
 assert.equal(h.sent.length,0);assert.equal(h.state.compactCalls,0);
});

for(const marker of ['DONE','NEEDS_INPUT']) {
 test(`${marker} file blocks recovery without changing the project`,async t=>{
  const h=harness(t);mkdirSync(join(h.cwd,'.pi'));writeFileSync(join(h.cwd,'.pi',marker),'stop');
  await h.emit('agent_settled');assert.equal(h.sent.length,0);assert.equal(h.branch.length,2);
 });
 test(`${marker} standalone final text blocks recovery`,async t=>{
  const h=harness(t,{text:`${marker}: Complete or blocked.`});await h.emit('agent_settled');assert.equal(h.sent.length,0);
 });
}

test('mentions of marker paths or markers in thinking are not terminal declarations',async t=>{
 const h=harness(t,{text:'Read .pi/DONE before continuing.'});h.branch[1].message.content.push({type:'thinking',thinking:'DONE'});
 await h.emit('agent_settled');assert.equal(h.sent.length,1);
});

test('queued human follow-up prevents duplicate recovery',async t=>{
 const h=harness(t);h.state.pending=true;await h.emit('agent_settled');assert.equal(h.sent.length,0);
});

for(const change of ['input','aborted','error','shutdown','marker','pending'])test(`compaction then ${change} -> no delayed continuation`,async t=>{
 const h=harness(t,{tokens:60000});await h.emit('agent_settled');
 if(change==='input')await h.emit('input',{source:'interactive',text:'Stop'});
 if(change==='aborted'||change==='error'){h.appendAssistant('terminal',change);await h.emit('agent_end',{messages:[h.branch.at(-1).message]});}
 if(change==='shutdown')await h.emit('session_shutdown');
 if(change==='marker'){mkdirSync(join(h.cwd,'.pi'));writeFileSync(join(h.cwd,'.pi','DONE'),'done');}
 if(change==='pending')h.state.pending=true;
 h.state.compactOptions.onComplete({});assert.equal(h.sent.length,0);
});

for(const sync of [false,true])test(`compaction failure (${sync?'throw':'callback'}) consumes budget, no retry loop`,async t=>{
 const h=harness(t,{tokens:60000});h.state.throwCompact=sync;await h.emit('agent_settled');
 if(!sync)h.state.compactOptions.onError(Error('failed'));
 h.load();await h.emit('agent_settled');assert.equal(h.sent.length,0);assert.equal(h.state.compactCalls,1);
});

test('unrelated model and later user message do not revive old length',async t=>{
 const h=harness(t);h.ctx.model.id='another-model';await h.emit('agent_settled');assert.equal(h.sent.length,0);
 h.ctx.model.id='qwen38-flash-next';h.branch.push({type:'message',id:'human2',message:{role:'user',content:'Wait'}});
 await h.emit('agent_settled');assert.equal(h.sent.length,0);
});

test('Qwen resume resets old thinking once, unrelated models are untouched',async t=>{
 const h=harness(t);await h.emit('session_start');assert.equal(h.state.thinking,'medium');
 h.state.thinking='high';h.ctx.model.id='another';await h.emit('session_start');assert.equal(h.state.thinking,'high');
});

test('switching to Qwen selects Medium, without forcing it on each ordinary turn',async t=>{
 const h=harness(t);h.state.thinking='high';await h.emit('model_select');assert.equal(h.state.thinking,'medium');
 h.state.thinking='high';await h.emit('input',{source:'interactive',text:'Use a deliberately chosen level'});assert.equal(h.state.thinking,'high');
});
