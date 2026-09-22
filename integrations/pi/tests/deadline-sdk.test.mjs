import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createAgentSession,DefaultResourceLoader,SettingsManager,SessionManager} from '@earendil-works/pi-coding-agent';

test('Pi SDK propagates a deadline into native bash, then exposes the failure to the model',{timeout:15000},async t=>{
 const root=mkdtempSync(join(tmpdir(),'pi-deadline-sdk-')),agentDir=join(root,'agent');mkdirSync(agentDir);
 const ext=join(root,'deadline.ts');
 writeFileSync(ext,`import {installDeadlines} from ${JSON.stringify(new URL('../extensions/qwen-tool-deadlines.ts',import.meta.url).pathname)}; export default function(pi){installDeadlines(pi,0.15);}`);
 const requests=[];
 const server=http.createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  const p=JSON.parse(body);requests.push(p);
  const base={id:'deadline-test',object:'chat.completion.chunk',created:1,model:'qwen38-flash-next'};
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  const emit=(delta,finish_reason=null)=>res.write(`data: ${JSON.stringify({...base,choices:[{index:0,delta,finish_reason}]})}\n\n`);
  emit({role:'assistant'});
  if(requests.length===1){
   emit({tool_calls:[{index:0,id:'hung-command',type:'function',function:{name:'bash',arguments:JSON.stringify({command:"node -e 'setInterval(() => {}, 1000)'"})}}]});emit({},'tool_calls');
  }else{
   const result=p.messages.findLast(m=>m.role==='tool');
   assert.match(JSON.stringify(result),/timed out|timeout/i);
   emit({content:'DONE: command timed out; no passing test claimed.'});emit({},'stop');
  }
  res.write(`data: ${JSON.stringify({...base,choices:[],usage:{prompt_tokens:100,completion_tokens:20,total_tokens:120}})}\n\n`);res.end('data: [DONE]\n\n');
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const provider={api:'openai-completions',baseUrl:`http://127.0.0.1:${server.address().port}/v1`,apiKey:'local',models:[{id:'qwen38-flash-next',name:'Test',contextWindow:131072,maxTokens:16384,input:['text'],reasoning:true,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]};
 writeFileSync(join(agentDir,'models.json'),JSON.stringify({providers:{'local-qwen':provider}}));
 const settings=SettingsManager.inMemory({defaultProvider:'local-qwen',defaultModel:'qwen38-flash-next',extensions:[ext],packages:[],retry:{enabled:false},defaultProjectTrust:'trust'});
 const loader=new DefaultResourceLoader({cwd:root,agentDir,settingsManager:settings,noSkills:true,noContextFiles:true});await loader.reload();
 const {session}=await createAgentSession({cwd:root,agentDir,settingsManager:settings,resourceLoader:loader,sessionManager:SessionManager.inMemory(root),tools:['bash']});
 t.after(async()=>{session.dispose();await new Promise(r=>server.close(r));rmSync(root,{recursive:true,force:true});});
 const errors=[];await session.bindExtensions({onError:e=>errors.push(String(e))});
 const started=Date.now();await session.prompt('Run the command once and report its actual result.');await session.waitForIdle();
 assert.equal(requests.length,2);assert.ok(Date.now()-started<5000);assert.deepEqual(errors,[]);
 const result=session.messages.find(m=>m.role==='toolResult');assert.equal(result.isError,true);
});
