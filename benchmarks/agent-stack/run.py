"""Run exactly one agent locally, then grade against out-of-repo acceptance tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
from fixtures import ROOT, prepare

BASE = os.environ.get('EVAL_BASE_URL', 'http://127.0.0.1:18319/v1')
UPSTREAM = os.environ.get('UPSTREAM', 'http://127.0.0.1:1919').rstrip('/')
MODEL = 'qwen38-flash-next'
HOME_DIR = Path.home()
PROMPT = 'Fix all bugs described in README.md. Follow AGENTS.md, add regression tests, run the checks and review your diff. Work autonomously until complete.'
GUARD = HOME_DIR / '.pi/agent/operations/QWEN_FLASH_NEXT_GUARDRAILS.md'

def config(agent, name):
    dest = ROOT / 'config' / name
    dest.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop('NODE_PATH', None)
    env.update({'NO_COLOR':'1', 'CI':'1', 'PWD':str(ROOT/'runs'/name)})
    if agent == 'pi':
        env['EVAL_BASE_URL'] = BASE
        cmd = ['node', str(ROOT/'pi-run.mjs'), str(ROOT/'runs'/name), str(ROOT/'results'/f'{name}.session.json'), str(dest)]
    elif agent == 'qwen':
        settings = {
            'security': {'auth': {'selectedType': 'openai'}},
            'model': {'name':MODEL, 'maxSessionTurns':32},
            'modelProviders': {'openai': [{
                'id':MODEL, 'name':'Local Flash Next', 'baseUrl':BASE, 'envKey':'EVAL_LOCAL_KEY',
                'generationConfig': {'contextWindowSize':131072,'timeout':600000,'maxRetries':0,
                    'samplingParams':{'temperature':1.0,'top_p':.95,'max_tokens':16384},
                    'extra_body':{'reasoning_effort':'medium','top_k':20,'min_p':0,'repetition_penalty':1,
                         'chat_template_kwargs':{'enable_thinking':True,'preserve_thinking':True,'reasoning_effort':'medium'}}}}]},
            'telemetry':{'enabled':False},
            'context':{'fileName':['AGENTS.md']},
            'general':{'enableAutoUpdate':False}
        }
        (dest/'settings.json').write_text(json.dumps(settings,indent=2))
        env.update({'QWEN_HOME':str(dest),'EVAL_LOCAL_KEY':'local','OPENAI_API_KEY':'local','OPENAI_BASE_URL':BASE,'OPENAI_MODEL':MODEL})
        cmd=[str(ROOT/'qwen-runtime/node_modules/.bin/qwen'),'--auth-type','openai','--model',MODEL,
             '--output-format','stream-json','--approval-mode','yolo','--max-session-turns','32',
             '--max-wall-time','10m','--max-tool-calls','64','--append-system-prompt',GUARD.read_text(),
             '--exclude-tools','task','--prompt',PROMPT]
    elif agent == 'opencode':
        existing=json.loads((HOME_DIR/'.config/opencode/opencode.jsonc').read_text())
        provider=existing['provider']['local-qwen-next'];provider['options']['baseURL']=BASE
        provider['models'][MODEL]['options']['chat_template_kwargs']['reasoning_effort']='medium'
        settings={
          '$schema':'https://opencode.ai/config.json','model':'local-qwen-next/'+MODEL,
          'small_model':'local-qwen-next/'+MODEL,'default_agent':'build','share':'disabled','autoupdate':False,
          'provider':{'local-qwen-next':provider},'instructions':[str(GUARD)],
          'compaction':{'auto':True,'prune':True,'reserved':32768},'lsp':False,'formatter':False,
          'agent':{'build':{'temperature':1.0,'top_p':.95,'steps':32}},
          'permission':{'read':'allow','edit':'allow','bash':'allow','glob':'allow','grep':'allow','list':'allow','task':'deny','webfetch':'deny','websearch':'deny','external_directory':'deny','doom_loop':'ask'}
        }
        (dest/'opencode.json').write_text(json.dumps(settings,indent=2))
        env.update({'XDG_CONFIG_HOME':str(dest/'xdg-config'),'XDG_DATA_HOME':str(dest/'xdg-data'),
                    'XDG_STATE_HOME':str(dest/'xdg-state'),'OPENCODE_CONFIG':str(dest/'opencode.json'),
                    'OPENCODE_DISABLE_PROJECT_CONFIG':'true'})
        cmd=['opencode','run','--dir',str(ROOT/'runs'/name),'--pure','--model','local-qwen-next/'+MODEL,'--agent','build','--variant','medium','--format','json',PROMPT]
    elif agent == 'dsh':
        extract="const fs=require('fs');const yaml=require(process.argv[2]+'/node_modules/yaml');const doc=yaml.parse(fs.readFileSync(process.argv[1],'utf8'));process.stdout.write(JSON.stringify(doc['llm-pi-ai'].providers['local-qwen-next']));"
        provider=json.loads(subprocess.check_output(['node','-e',extract,str(HOME_DIR/'.dsh/settings.yaml'),os.environ['DSH_ROOT']],env=env,text=True))
        provider['baseURL']=BASE;provider['apiKeyEnv']='EVAL_LOCAL_KEY'
        settings={'agent-default-model':{'provider':'local-qwen-next','model':MODEL,'reasoningEffort':'medium'},
                  'llm-pi-ai':{'providers':{'local-qwen-next':provider}}}
        (dest/'settings.json').write_text(json.dumps(settings,indent=2))
        patch=[{'id':'settings','config':{'path':str(dest/'settings.json'),'watch':False}},
               {'id':'session-persistence-jsonl','config':{'root':str(dest/'sessions')}},
               {'id':'tool-subagent','disabled':True}, {'id':'tool-fork','disabled':True}]
        (dest/'patch.yaml').write_text(json.dumps(patch,indent=2))
        env.update({'EVAL_LOCAL_KEY':'local','DSH_TELEMETRY_DISABLED':'1','DSH_PERMISSION_MODE':'danger-full-access'})
        cmd=['dsh','--profile','headless','--patch',str(dest/'patch.yaml'),PROMPT]
    else: raise ValueError(agent)
    return cmd, env

def grade(name, task, repo):
    env=os.environ.copy();env['CANDIDATE']=str(repo)
    cmd=['python3',str(ROOT/'accept_cache.py')] if task=='cache' else ['node','--test',str(ROOT/'accept_history.mjs')]
    try:
        result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20)
        text=result.stdout+result.stderr; code=result.returncode
    except subprocess.TimeoutExpired:
        text='Acceptance timed out';code=124
    (ROOT/'results'/f'{name}.acceptance.txt').write_text(text)
    public_cmd=['python3','-m','unittest','discover','-s','tests','-v'] if task=='cache' else ['node','--test',*map(str,sorted((repo/'tests').glob('*.test.mjs')))]
    try:
        public=subprocess.run(public_cmd,cwd=repo,capture_output=True,text=True,timeout=15,start_new_session=True)
        public_text=public.stdout+public.stderr;public_code=public.returncode
    except subprocess.TimeoutExpired:
        public_text='Candidate tests timed out after 15 seconds';public_code=124
    (ROOT/'results'/f'{name}.public.txt').write_text(public_text)
    manifest=json.loads((ROOT/'results'/f'{name}.manifest.json').read_text())
    intact=all((repo/p).exists() and hashlib.sha256((repo/p).read_bytes()).hexdigest()==sha for p,sha in manifest.items())
    diff=subprocess.run(['git','diff','--stat'],cwd=repo,capture_output=True,text=True).stdout
    status=subprocess.run(['git','status','--short'],cwd=repo,capture_output=True,text=True).stdout
    return {'acceptance_exit':code,'public_tests_exit':public_code,'protected_files_intact':intact,'diff_stat':diff,'git_status':status,'passed':code==0 and public_code==0 and intact}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('agent');parser.add_argument('task',choices=['cache','history']);parser.add_argument('--grade-only',action='store_true')
    args=parser.parse_args();name=args.agent+'-'+args.task;repo=ROOT/'runs'/name
    if args.grade_only:
        print(json.dumps(grade(name,args.task,repo),indent=2));return
    stats=json.load(urllib.request.urlopen(UPSTREAM + '/v1/stats',timeout=10))
    if stats['requests']['active']:raise SystemExit('Model busy: refusing overlapping benchmark')
    repo=prepare(args.task,args.agent);cmd,env=config(args.agent,name)
    (ROOT/'active-trial').write_text(name)
    started=time.monotonic();timeout=False
    with (ROOT/'results'/f'{name}.log').open('w') as log:
        proc=subprocess.Popen(cmd,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try: code=proc.wait(timeout=630)
        except subprocess.TimeoutExpired:
            timeout=True;os.killpg(proc.pid,signal.SIGTERM)
            try:code=proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);code=proc.wait()
    if args.agent=='qwen' and 'wall-clock budget' in (ROOT/'results'/f'{name}.log').read_text()[-4000:]:
        timeout=True
    session_path=ROOT/'results'/f'{name}.session.json'
    if args.agent=='pi' and session_path.exists():
        timeout=timeout or json.loads(session_path.read_text()).get('timedOut',False)
    result={'agent':args.agent,'task':args.task,'elapsed_s':round(time.monotonic()-started,3),'exit':code,'timeout':timeout,**grade(name,args.task,repo)}
    result['passed'] = result['passed'] and code == 0 and not timeout
    (ROOT/'results'/f'{name}.result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
