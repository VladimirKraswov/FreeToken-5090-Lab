#!/usr/bin/env python3
"""Start the dedicated loopback OpenCode UI once, then open it."""
import fcntl,json,os,shutil,socket,subprocess,sys,time,urllib.request
from pathlib import Path
URL='http://127.0.0.1:4096'
STATE=Path.home()/'.local/state/qwen-opencode'
STATE.mkdir(parents=True,exist_ok=True)
def health():
 try:
  with urllib.request.urlopen(URL+'/global/health',timeout=2) as r:
   d=json.load(r)
  return d.get('healthy') is True and isinstance(d.get('version'),str)
 except Exception:return False
with (STATE/'launch.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if not health():
  with socket.socket() as sock:
   if sock.connect_ex(('127.0.0.1',4096))==0:raise SystemExit('Port 4096 is occupied by a different or unhealthy service.')
  executable=shutil.which('opencode')
  if not executable:raise SystemExit('opencode is not installed or not on PATH')
  env=os.environ.copy();env.pop('NODE_PATH',None);env['PWD']=str(Path.home());env['NO_COLOR']='1'
  with (STATE/'server.log').open('ab') as log:
   child=subprocess.Popen([executable,'serve','--hostname','127.0.0.1','--port','4096'],cwd=Path.home(),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  (STATE/'pid').write_text(str(child.pid))
  for _ in range(100):
   if health():break
   if child.poll() is not None:raise SystemExit('OpenCode exited; see '+str(STATE/'server.log'))
   time.sleep(.2)
  else:raise SystemExit('OpenCode did not become ready; see '+str(STATE/'server.log'))
if '--no-open' not in sys.argv:subprocess.run(['open',URL],check=True)
print(URL)
