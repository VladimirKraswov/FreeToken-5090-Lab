"""Small, dependency-free agent acceptance suite; not a frontier benchmark."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
COMMON = '''Work only in this repository. Read README.md and inspect Git before editing.
Fix the requested behavior and add meaningful regression tests. Do not change or
remove existing tests, user-notes.txt, or this file. Do not install dependencies,
use the network, delegate to other agents, or inspect directories outside this
repository. Use the existing standard-library test runner. Review your diff and
report the actual checks you ran. A short useful tool action should precede long
speculation. Preserve user changes. Do not commit. Do not ask follow-up questions;
all requirements are in README.md. Finish when the implementation and tests pass.
'''

CACHE = {
'README.md': '''# Async value cache
Fix AsyncCache in cache.py while preserving its public API:
`AsyncCache(ttl, clock=time.monotonic)`; `await get(key, async_loader)`;
`clear()` invalidates stored values and in-flight cache ownership.

Reported bugs: cancelling one HTTP request cancels another request for the same
key; clear during a load can resurrect stale values; expiry sometimes happens
before a slow load finishes. Values including None must be cached. Concurrent
callers for one key share exactly one load; different keys do not block each other.
TTL starts at successful completion, an entry expires at clock >= expiry, and a
loader failure is never cached. Cancelling a waiter must not cancel the shared
loader, including when that waiter was the last waiter. A clear does not cancel
existing callers: they may receive their old result, but callers after clear use
a new load, and an old load cannot overwrite/remove a new generation. No global
locks around awaits. Keep it single-event-loop, dependency-free, no background
polling. Test with `python3 -m unittest discover -s tests -v`.
''',
'cache.py': '''import asyncio
import time

class AsyncCache:
    def __init__(self, ttl, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self.values = {}
        self.pending = {}

    async def get(self, key, loader):
        value, expiry = self.values.get(key, (None, 0))
        if value is not None and self.clock() < expiry:
            return value
        if key not in self.pending:
            async def load():
                expiry = self.clock() + self.ttl
                try:
                    value = await loader()
                    self.values[key] = (value, expiry)
                    return value
                finally:
                    self.pending.pop(key, None)
            self.pending[key] = asyncio.create_task(load())
        return await self.pending[key]

    def clear(self):
        self.values.clear()
''',
'tests/test_basic.py': '''import unittest
from cache import AsyncCache

class Basic(unittest.IsolatedAsyncioTestCase):
    async def test_reuse(self):
        calls = []
        async def load():
            calls.append(1)
            return "value"
        cache = AsyncCache(10)
        self.assertEqual(await cache.get("a", load), "value")
        self.assertEqual(await cache.get("a", load), "value")
        self.assertEqual(len(calls), 1)
'''
}

HISTORY = {
'README.md': '''# Geometry editor gesture history
Fix GestureHistory in history.mjs without changing the API. This is the model
layer used by a pointer-based editor; there is no DOM and no browser dependency.
Run public tests with `node --test tests/*.test.mjs`.

State is a JSON-serializable document. constructor(initial), state getter,
begin(pointerId), update(pointerId, next), commit(pointerId), cancel(pointerId),
undo(), redo(). Methods return true only when they actually perform the relevant
operation (a matching commit/cancel ends an active gesture and returns true,
including an unchanged commit). Idle/foreign updates, commits or cancellations
return false. begin while any gesture is active returns false. Foreign pointers
must never steal ownership. update changes the live preview; commit saves exactly
one undo step for a whole changed gesture, cancel restores its starting state.
A structurally unchanged commit or a cancel must preserve the redo stack.
A changed commit clears redo. undo/redo while dragging return false and leave
the live gesture untouched. No-op undo/redo return false. All input documents and
returned state must be defensively copied, including nested arrays/objects; users
must not mutate history via an object reference. Structural equality ignores
object key order but respects array order and distinguishes missing keys vs null.
Preserve the API and keep this module dependency-free.
''',
'history.mjs': '''export class GestureHistory {
  constructor(initial) { this.current = initial; this.past = []; this.future = []; this.active = null; }
  get state() { return this.current; }
  begin(pointerId) { this.active = { pointerId, start: this.current }; return true; }
  update(pointerId, next) { if (!this.active) return false; this.current = next; return true; }
  commit(pointerId) {
    if (!this.active) return false;
    this.past.push(this.active.start); this.future = []; this.active = null; return true;
  }
  cancel(pointerId) { if (!this.active) return false; this.current = this.active.start; this.active = null; return true; }
  undo() { if (!this.past.length) return false; this.future.push(this.current); this.current = this.past.pop(); return true; }
  redo() { if (!this.future.length) return false; this.past.push(this.current); this.current = this.future.pop(); return true; }
}
''',
'tests/basic.test.mjs': '''import test from 'node:test';
import assert from 'node:assert/strict';
import { GestureHistory } from '../history.mjs';
test('commit can be undone and redone', () => {
  const h = new GestureHistory({x: 0});
  assert.equal(h.begin(1), true); h.update(1, {x: 3}); h.commit(1);
  assert.equal(h.undo(), true); assert.deepEqual(h.state, {x: 0});
  assert.equal(h.redo(), true); assert.deepEqual(h.state, {x: 3});
});
'''
}

def prepare(task, agent):
    target = ROOT / 'runs' / f'{agent}-{task}'
    if target.exists():
        raise SystemExit(f'Refusing to overwrite {target}')
    target.mkdir(parents=True)
    files = dict(CACHE if task == 'cache' else HISTORY)
    files['AGENTS.md'] = COMMON
    files['.gitignore'] = '__pycache__/\n.pytest_cache/\n'
    for name, content in files.items():
        p = target / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(['git', 'init', '-q', str(target)], check=True)
    subprocess.run(['git', 'add', '.'], cwd=target, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-qm', 'fixture baseline'], cwd=target, check=True)
    (target / 'user-notes.txt').write_text('Uncommitted user note: do not alter.\n')
    manifest = {name: hashlib.sha256((target / name).read_bytes()).hexdigest()
                for name in files if name.startswith('tests/') or name in ['README.md', 'AGENTS.md']}
    manifest['user-notes.txt'] = hashlib.sha256((target / 'user-notes.txt').read_bytes()).hexdigest()
    (ROOT / 'results').mkdir(exist_ok=True)
    (ROOT / 'results' / f'{agent}-{task}.manifest.json').write_text(json.dumps(manifest, indent=2))
    return target

if __name__ == '__main__':
    print(prepare(*sys.argv[1:3]))
