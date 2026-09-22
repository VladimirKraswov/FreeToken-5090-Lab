import type {ExtensionAPI} from '@earendil-works/pi-coding-agent';
import {Type} from 'typebox';
import {join} from 'node:path';
import {homedir} from 'node:os';
export default function(pi:ExtensionAPI){
 pi.registerTool({
  name:'repo_inspect',label:'Inspect repository checks',
  description:'Read-only overview of the current repository: Git status/diff statistics, manifests, test directories and available npm script names. Does not run project code or change files.',
  parameters:Type.Object({}),
  async execute(_id,_args,signal,_update,ctx){
   const result=await pi.exec('python3',[join(homedir(),'.pi/agent/skills/qwen-verify-change/scripts/repo_inspect.py'),'--root',ctx.cwd],{signal,timeout:20000});
   return {content:[{type:'text',text:result.stdout||result.stderr}],details:{exitCode:result.code}};
  }
 });
}
