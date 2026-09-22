#!/usr/bin/env python3
"""Bounded repository metadata inspection; does not run project code."""
import argparse,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',default='.');args=p.parse_args();root=Path(args.root).resolve()
if not root.is_dir():p.error('root is not a directory')
def git(*args):
 try:
  r=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,timeout=10)
  return {'exit_code':r.returncode,'output':r.stdout[:12000].splitlines()[:120]}
 except (OSError,subprocess.TimeoutExpired) as e:return {'error':type(e).__name__}
manifest_names=['package.json','pnpm-lock.yaml','package-lock.json','yarn.lock','bun.lock','bun.lockb','pyproject.toml','pytest.ini','tox.ini','requirements.txt','Cargo.toml','go.mod','Makefile','justfile','CMakeLists.txt','composer.json','Gemfile']
report={'root':str(root),'manifests':[x for x in manifest_names if (root/x).is_file()],'instruction_files':[x for x in ['AGENTS.md','CLAUDE.md','.pi/TASK.md','.opencode/TASK.md','.dsh/TASK.md'] if (root/x).is_file()],'test_directories':[x for x in ['test','tests','__tests__','e2e','spec'] if (root/x).is_dir()],'git_status':git('status','--short'),'diff_stat':git('diff','--stat'),'staged_diff_stat':git('diff','--cached','--stat')}
package=root/'package.json'
if package.is_file() and not package.is_symlink() and package.stat().st_size<1024*1024:
 try:
  data=json.loads(package.read_text());report['package_manager']=data.get('packageManager');report['npm_script_names']=sorted(data.get('scripts',{}))
 except (ValueError,OSError):report['manifest_error']='Cannot parse package.json'
print(json.dumps(report,ensure_ascii=False,indent=2))
