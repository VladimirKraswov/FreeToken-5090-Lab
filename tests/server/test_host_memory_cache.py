"""A slow /proc/PSS reader must not block streams or multiply with polling clients."""
import asyncio
import threading

from freetoken.server.host_memory_cache import HostMemoryCache


def test_cold_pollers_share_one_read_and_event_loop_remains_live():
    async def check():
        entered, release = threading.Event(), threading.Event()
        calls = []
        def loader():
            calls.append(1)
            entered.set()
            assert release.wait(2)
            return {"engine_bytes": 123}
        cache = HostMemoryCache(loader)
        tasks = [asyncio.create_task(cache.get()) for _ in range(20)]
        try:
            while not entered.is_set():
                await asyncio.sleep(.001)
            # This coroutine progresses even while the reader's thread is blocked.
            assert not any(task.done() for task in tasks)
            release.set()
            results = await asyncio.gather(*tasks)
            assert calls == [1]
            assert all(value == {"engine_bytes": 123} and age >= 0 and not refreshing
                       for value, age, refreshing in results)
            assert (await cache.get())[0] == {"engine_bytes": 123}
            assert calls == [1]
        finally:
            release.set()
    asyncio.run(asyncio.wait_for(check(), 3))


def test_disconnect_does_not_cancel_shared_refresh():
    async def check():
        entered, release = threading.Event(), threading.Event()
        def loader():
            entered.set()
            assert release.wait(2)
            return {"engine_bytes": 321}
        cache = HostMemoryCache(loader)
        one, two = asyncio.create_task(cache.get()), asyncio.create_task(cache.get())
        try:
            while not entered.is_set():
                await asyncio.sleep(.001)
            one.cancel()
            try:
                await one
            except asyncio.CancelledError:
                pass
            release.set()
            assert (await two)[0] == {"engine_bytes": 321}
            assert (await cache.get())[0] == {"engine_bytes": 321}
        finally:
            release.set()
    asyncio.run(asyncio.wait_for(check(), 3))


def test_warm_poll_returns_stale_data_during_single_refresh():
    async def check():
        entered, release = threading.Event(), threading.Event()
        calls = []
        def loader():
            calls.append(1)
            if len(calls) > 1:
                entered.set()
                assert release.wait(2)
            return {"engine_bytes": len(calls)}
        cache = HostMemoryCache(loader)
        assert (await cache.get())[0] == {"engine_bytes": 1}
        cache._last_attempt_at -= 11
        try:
            for _ in range(20):
                value, age, refreshing = await cache.get()
                assert value == {"engine_bytes": 1} and refreshing and age >= 0
            while not entered.is_set():
                await asyncio.sleep(.001)
            assert calls == [1, 1]
            release.set()
            while cache._task is not None:
                await asyncio.sleep(.001)
            assert (await cache.get())[0] == {"engine_bytes": 2}
        finally:
            release.set()
    asyncio.run(asyncio.wait_for(check(), 3))


def test_failed_read_is_bounded_and_keeps_sample_age(caplog):
    async def check():
        calls = []
        def loader():
            calls.append(1)
            if len(calls) > 1:
                raise OSError("process vanished")
            return {"engine_bytes": 17}
        cache = HostMemoryCache(loader)
        await cache.get()
        sampled_at = cache._sampled_at
        cache._last_attempt_at -= 11
        await cache.get()
        while cache._task is not None:
            await asyncio.sleep(.001)
        for _ in range(20):
            assert (await cache.get())[0] == {"engine_bytes": 17}
        assert len(calls) == 2 and cache._sampled_at == sampled_at
        assert "Host memory refresh failed" in caplog.text
    asyncio.run(asyncio.wait_for(check(), 3))


def test_missing_proc_can_return_none_without_repeated_reads():
    async def check():
        calls = []
        cache = HostMemoryCache(lambda: calls.append(1))
        value, age, refreshing = await cache.get()
        assert value is None and age >= 0 and not refreshing
        assert (await cache.get())[0] is None
        assert len(calls) == 1
    asyncio.run(asyncio.wait_for(check(), 3))
