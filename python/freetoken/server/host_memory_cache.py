"""Bound expensive process-tree PSS reads without blocking the serving event loop."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable


class HostMemoryCache:
    """One refresh at a time; cold readers await it, warm readers use the last sample.

    A disconnected reader cannot cancel the shared refresh. The cache is owned
    by one API event loop; the loader runs in its thread pool and never accesses
    FrontendManager or scheduler state.
    """

    def __init__(self, loader: Callable[[], dict | None], ttl_s: float = 10.0) -> None:
        self._loader = loader
        self._ttl_s = ttl_s
        self._value: dict | None = None
        self._sampled_at: float | None = None
        self._task: asyncio.Task | None = None
        self._last_attempt_at: float | None = None
        self._initialized = False

    async def _refresh(self) -> None:
        try:
            self._value = await asyncio.to_thread(self._loader)
            self._sampled_at = time.monotonic()
        except Exception:
            logging.getLogger(__name__).warning("Host memory refresh failed; retaining the last sample", exc_info=True)
        finally:
            self._last_attempt_at = time.monotonic()
            self._initialized = True
            self._task = None

    async def get(self) -> tuple[dict | None, float | None, bool]:
        now = time.monotonic()
        if self._task is None and (self._last_attempt_at is None or now - self._last_attempt_at >= self._ttl_s):
            self._task = asyncio.create_task(self._refresh())
        if not self._initialized:
            # Only a cold cache waits. Shield protects other callers on disconnect.
            await asyncio.shield(self._task)
        age = None if self._sampled_at is None else max(0.0, time.monotonic() - self._sampled_at)
        return self._value, age, self._task is not None
