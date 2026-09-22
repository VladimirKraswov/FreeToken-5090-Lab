import asyncio
import importlib.util
import os
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('candidate', Path(os.environ['CANDIDATE']) / 'cache.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
AsyncCache = mod.AsyncCache

async def tick():
    for _ in range(5):
        await asyncio.sleep(0)

class Acceptance(unittest.IsolatedAsyncioTestCase):
    async def test_none_is_a_value_and_exact_expiry(self):
        now = [10.0]; calls = []
        async def load(): calls.append(1); return None
        cache = AsyncCache(2, lambda: now[0])
        await cache.get('a', load); now[0] = 11.99; await cache.get('a', load)
        self.assertEqual(len(calls), 1)
        now[0] = 12; await cache.get('a', load)
        self.assertEqual(len(calls), 2)

    async def test_completion_based_ttl(self):
        now = [0]; calls = []
        async def load(): calls.append(1); now[0] += 20; return 'x'
        c = AsyncCache(5, lambda: now[0]); await c.get('x', load)
        now[0] = 24; await c.get('x', load)
        self.assertEqual(len(calls), 1)
        now[0] = 25; await c.get('x', load)
        self.assertEqual(len(calls), 2)

    async def test_coalescing_and_waiter_cancellation(self):
        gate = asyncio.Event(); calls = []
        async def load(): calls.append(1); await gate.wait(); return 'ok'
        c = AsyncCache(10)
        a = asyncio.create_task(c.get('k', load)); b = asyncio.create_task(c.get('k', load))
        await tick(); a.cancel()
        with self.assertRaises(asyncio.CancelledError): await a
        gate.set()
        self.assertEqual(await asyncio.wait_for(b, 1), 'ok')
        self.assertEqual(len(calls), 1)

    async def test_last_waiter_cancel_does_not_cancel_loader(self):
        gate = asyncio.Event(); calls = []
        async def load(): calls.append(1); await gate.wait(); return 3
        c = AsyncCache(10); a = asyncio.create_task(c.get('a', load)); await tick(); a.cancel()
        with self.assertRaises(asyncio.CancelledError): await a
        gate.set(); await tick()
        self.assertEqual(await c.get('a', load), 3); self.assertEqual(len(calls), 1)

    async def test_keys_do_not_serialize(self):
        gate = asyncio.Event()
        async def slow(): await gate.wait(); return 'a'
        async def fast(): return 'b'
        c = AsyncCache(1); a = asyncio.create_task(c.get('a', slow)); await tick()
        try: self.assertEqual(await asyncio.wait_for(c.get('b', fast), .3), 'b')
        finally: gate.set(); await a

    async def test_failure_not_cached(self):
        calls = []
        async def load():
            calls.append(1)
            if len(calls) == 1: raise ValueError('boom')
            return 7
        c = AsyncCache(2)
        with self.assertRaises(ValueError): await c.get('a', load)
        self.assertEqual(await c.get('a', load), 7)
        self.assertEqual(len(calls), 2)

    async def test_clear_during_load_new_finishes_first(self):
        gate = asyncio.Event(); calls = []
        async def old(): await gate.wait(); return 'old'
        async def new(): calls.append(1); return 'new'
        c = AsyncCache(10); a = asyncio.create_task(c.get('k', old)); await tick(); c.clear()
        b = asyncio.create_task(c.get('k', new)); await tick(); gate.set()
        self.assertEqual(await asyncio.wait_for(b, 1), 'new')
        self.assertEqual(await a, 'old')
        self.assertEqual(await c.get('k', new), 'new'); self.assertEqual(len(calls), 1)

    async def test_old_completion_does_not_remove_new_pending(self):
        ga, gb = asyncio.Event(), asyncio.Event(); calls = []
        async def old(): await ga.wait(); return 'old'
        async def new(): calls.append(1); await gb.wait(); return 'new'
        c = AsyncCache(10); a = asyncio.create_task(c.get('k', old)); await tick(); c.clear()
        b = asyncio.create_task(c.get('k', new)); await tick(); ga.set(); await a
        d = asyncio.create_task(c.get('k', new)); await tick(); gb.set()
        self.assertEqual(await b, 'new'); self.assertEqual(await d, 'new')
        self.assertEqual(len(calls), 1)

if __name__ == '__main__': unittest.main(verbosity=2)
