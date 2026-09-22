import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {homedir} from 'node:os';
import {join,resolve} from 'node:path';
const {createAgentSession,DefaultResourceLoader,SettingsManager,SessionManager}=await import(process.env.PI_SDK_URL || '@earendil-works/pi-coding-agent');
const cwd=resolve(process.argv[2]), output=resolve(process.argv[3]), agentDir=resolve(process.argv[4]);
mkdirSync(agentDir,{recursive:true});
const config=JSON.parse(readFileSync(join(homedir(),'.pi/agent/models.json'),'utf8'));
config.providers['local-qwen'].baseUrl=process.env.EVAL_BASE_URL || 'http://127.0.0.1:1919/v1';
writeFileSync(join(agentDir,'models.json'),JSON.stringify({providers:{'local-qwen':config.providers['local-qwen']}}));
const settings=SettingsManager.inMemory({defaultProvider:'local-qwen',defaultModel:'qwen38-flash-next',defaultThinkingLevel:'medium',extensions:[],packages:[],compaction:{enabled:true,reserveTokens:49152,keepRecentTokens:16000},retry:{enabled:false},defaultProjectTrust:'trust'});
const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager:settings,noSkills:true,noPromptTemplates:true,noThemes:true,appendSystemPrompt:[readFileSync(join(homedir(),'.pi/agent/operations/QWEN_FLASH_NEXT_GUARDRAILS.md'),'utf8')]});
await loader.reload();
const {session}=await createAgentSession({cwd,agentDir,settingsManager:settings,resourceLoader:loader,sessionManager:SessionManager.inMemory(cwd),tools:['read','bash','edit','write','grep','find','ls'],thinkingLevel:'medium'});
const started=Date.now();let turns=0,toolCalls=0,firstAction=null;const errors=[];
session.subscribe(event=>{
 if(event.type==='tool_execution_start'){toolCalls++;firstAction??=(Date.now()-started)/1000;console.log(JSON.stringify({event:'tool',tool:event.toolName,t:Date.now()-started}));}
 if(event.type==='turn_end' && ++turns>=32)void session.abort();
});
let timedOut=false;const timer=setTimeout(()=>{timedOut=true;void session.abort();},600000);
try {
 await session.prompt('Fix all bugs described in README.md. Follow AGENTS.md, add regression tests, run the checks and review your diff. Work autonomously until complete.');await session.waitForIdle();
 const messages=session.messages;writeFileSync(output,JSON.stringify({elapsed_s:(Date.now()-started)/1000,first_action_s:firstAction,toolCalls,turns,thinking:session.thinkingLevel,timedOut,messages},null,2));
 console.log(JSON.stringify({complete:true,elapsed_s:(Date.now()-started)/1000,turns,toolCalls,stop:messages.filter(x=>x.role==='assistant').at(-1)?.stopReason}));
 if(messages.filter(x=>x.role==='assistant').at(-1)?.stopReason!=='stop')process.exitCode=1;
}finally{clearTimeout(timer);session.dispose();}
