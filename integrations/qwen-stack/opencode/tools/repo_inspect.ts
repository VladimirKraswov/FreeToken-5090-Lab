import {tool} from '@opencode-ai/plugin';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {join} from 'node:path';
import {homedir} from 'node:os';
export default tool({
 description:'Read-only repository overview: Git status/diff statistics, manifests, test directories and npm script names. Does not run project code or change files.',
 args:{},
 async execute(_args,context){
  const result=await promisify(execFile)('python3',[join(homedir(),'.config/opencode/skills/qwen-verify-change/scripts/repo_inspect.py'),'--root',context.directory],{signal:context.abort,timeout:20000,maxBuffer:65536});
  return result.stdout;
 }
});
