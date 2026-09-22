import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtempSync,mkdirSync,writeFileSync,symlinkSync,rmSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createAgentSession,DefaultResourceLoader,SettingsManager,SessionManager} from '@earendil-works/pi-coding-agent';
import {RECOVERY_PROMPT,STATE_TYPE} from '../extensions/autonomous-recovery.ts';
const extension=fileURLToPath(new URL('../extensions/autonomous-recovery.ts',import.meta.url));

function respond(res,{content='',thinking='',tools,stop='stop',input=15,output=12}){
 const base={id:'chatcmpl-local-test',object:'chat.completion.chunk',created:1,model:'qwen38-flash-next'};
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 const chunk=(delta,finish_reason=null)=>res.write(`data: ${JSON.stringify({...base,choices:[{index:0,delta,finish_reason}]})}\n\n`);
 chunk({role:'assistant'});
 if(thinking)chunk({reasoning_content:thinking});
 if(content)chunk({content});
 if(tools)chunk({tool_calls:tools.map((tool,index)=>({index,id:'call-'+index,type:'function',function:{name:tool.name,arguments:JSON.stringify(tool.args)}}))});
 chunk({},stop);
 res.write(`data: ${JSON.stringify({...base,choices:[],usage:{prompt_tokens:input,completion_tokens:output,total_tokens:input+output}})}\n\n`);
 res.end('data: [DONE]\n\n');
}

for(const scenario of ['length-tools','compact-tools','length-again'])test(`Pi SDK integration: ${scenario}`,{timeout:30000},async t=>{
 const root=mkdtempSync(join(tmpdir(),'pi-recovery-sdk-')),cwd=join(root,'work'),agentDir=join(root,'agent');
 mkdirSync(join(cwd,'.pi'),{recursive:true});mkdirSync(join(agentDir,'extensions'),{recursive:true});
 writeFileSync(join(cwd,'.pi/TASK.md'),'# Test task\nRead this checkpoint and inspect Git.\n');
 execFileSync('git',['init','--quiet'],{cwd});
 symlinkSync(extension,join(agentDir,'extensions/autonomous-recovery.ts'));
 const requests=[],errors=[];let phase=0;
 const server=http.createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  const p=JSON.parse(body);requests.push(p);
  if(phase===0){phase++;return respond(res,{thinking:'Truncated reasoning only.',stop:'length',input:scenario==='compact-tools'?50000:24785,output:16384});}
  const recovering=p.messages.some(m=>m.role==='user'&&(typeof m.content==='string'?m.content:(m.content??[]).filter(b=>b.type==='text').map(b=>b.text).join('\n'))===RECOVERY_PROMPT);
  if(scenario==='compact-tools'&&phase===1){
   assert.equal(recovering,false,'must compact before injecting continuation');phase++;
   return respond(res,{content:'## Goal\nRead .pi/TASK.md and inspect Git.\n## Progress\nNo changes yet.\n## Next Steps\nRead the task file and run git status.'});
  }
  assert.equal(recovering,true,'exact recovery instruction must reach provider');
  if(scenario==='length-again'){phase++;return respond(res,{thinking:'Still truncated.',stop:'length',output:16384});}
  if(!p.messages.some(m=>m.role==='tool')){
   phase++;return respond(res,{tools:[{name:'read',args:{path:'.pi/TASK.md'}},{name:'bash',args:{command:'git status --short'}}],stop:'tool_calls'});
  }
  phase++;return respond(res,{content:'DONE: Read checkpoint and inspected Git.'});
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const port=server.address().port;
 writeFileSync(join(agentDir,'models.json'),JSON.stringify({providers:{'local-qwen':{api:'openai-completions',baseUrl:`http://127.0.0.1:${port}/v1`,apiKey:'local',compat:{supportsDeveloperRole:false,supportsReasoningEffort:true,maxTokensField:'max_tokens',requiresReasoningContentOnAssistantMessages:true},models:[{id:'qwen38-flash-next',name:'Test Qwen',reasoning:true,thinkingLevelMap:{low:'low',medium:'medium',high:'xhigh'},input:['text'],contextWindow:131072,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}}));
 const settings=SettingsManager.inMemory({defaultProvider:'local-qwen',defaultModel:'qwen38-flash-next',defaultThinkingLevel:'medium',packages:[],extensions:[extension],compaction:{enabled:false,keepRecentTokens:100,reserveTokens:16384},retry:{enabled:false},defaultProjectTrust:'trust'});
 const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager:settings,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true});
 await loader.reload();
 const manager=SessionManager.inMemory(cwd);
 if(scenario==='compact-tools'){
  manager.appendMessage({role:'user',content:[{type:'text',text:'Earlier task'}],timestamp:1});
  manager.appendMessage({role:'assistant',api:'openai-completions',provider:'local-qwen',model:'qwen38-flash-next',stopReason:'stop',timestamp:2,content:[{type:'text',text:'Previously verified progress. '.repeat(100)}],usage:{input:10,output:100,cacheRead:0,cacheWrite:0,totalTokens:110,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
 }
 const {session,extensionsResult}=await createAgentSession({cwd,agentDir,settingsManager:settings,resourceLoader:loader,sessionManager:manager,tools:['read','bash'],thinkingLevel:'medium'});
 t.after(async()=>{session.dispose();await new Promise(r=>server.close(r));rmSync(root,{recursive:true,force:true});});
 assert.deepEqual(extensionsResult.errors,[]);
 assert.equal(extensionsResult.extensions.length,1,'auto discovery plus explicit path must deduplicate');
 const toolCalls=[];session.subscribe(event=>{if(event.type==='tool_execution_start')toolCalls.push(event.toolName);});
 await session.bindExtensions({onError:error=>errors.push(error)});
 await session.prompt('Read the checkpoint and inspect Git, then stop.');
 await session.waitForIdle();
 // A settled-hook continuation starts asynchronously after the first prompt unwinds.
 for(let i=0;i<100&&requests.length<(scenario==='length-again'?2:scenario==='compact-tools'?4:3);i++){
  await new Promise(r=>setTimeout(r,20));await session.waitForIdle();
 }
 assert.deepEqual(errors,[]);
 const branch=session.sessionManager.getBranch();
 const injected=branch.filter(e=>e.type==='message'&&e.message.role==='user'&&e.message.content.some(b=>b.type==='text'&&b.text===RECOVERY_PROMPT));
 assert.equal(injected.length,1,'exactly one recovery user message; states='+JSON.stringify(branch.filter(e=>e.type==='custom').map(e=>e.data))+'; errors='+JSON.stringify(errors));
 assert.equal(branch.filter(e=>e.type==='custom'&&e.customType===STATE_TYPE&&e.data.status==='reserved').length,1);
 assert.equal(requests.length,scenario==='length-again'?2:scenario==='compact-tools'?4:3);
 const ordinary=requests.filter(p=>p.tools?.length);
 assert.equal(ordinary[0].reasoning_effort,'medium');
 assert.ok(ordinary.slice(1).every(p=>p.reasoning_effort==='low'));
 assert.equal(session.thinkingLevel,'medium');
 assert.ok(ordinary.every(p=>p.max_tokens===16384),JSON.stringify(ordinary.map(p=>p.max_tokens)));
 if(scenario!=='length-again')assert.deepEqual(toolCalls,['read','bash']);
 if(scenario==='compact-tools')assert.equal(branch.filter(e=>e.type==='compaction').length,1);
 assert.equal(readFileSync(join(cwd,'.pi/TASK.md'),'utf8'),'# Test task\nRead this checkpoint and inspect Git.\n');
});
