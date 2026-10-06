from __future__ import annotations

import math


class FairBatchPolicy:
    """One prompt-prefill batch, then a bounded burst of completed generation batches."""

    def __init__(self, decode_burst_ms: float, decode_burst_steps: int):
        if not math.isfinite(decode_burst_ms) or decode_burst_ms <= 0:
            raise ValueError("scheduler_decode_burst_ms must be finite and positive")
        if decode_burst_steps <= 0:
            raise ValueError("scheduler_decode_burst_steps must be positive")
        self.decode_burst_seconds = decode_burst_ms / 1000
        self.decode_burst_steps = decode_burst_steps
        self.reset()

    def reset(self) -> None:
        self._generation_turn = False
        self._generation_seconds = 0.0
        self._generation_steps = 0

    def prefer_generation(self, *, prefill_pending: bool, generation_runnable: bool) -> bool:
        if not (prefill_pending and generation_runnable):
            self.reset()
            return generation_runnable
        return self._generation_turn

    def completed(self, *, generation: bool, elapsed_seconds: float) -> None:
        if not generation:
            self.reset()
            self._generation_turn = True
        elif self._generation_turn:
            self._generation_seconds += max(0.0, elapsed_seconds)
            self._generation_steps += 1
            if (self._generation_seconds >= self.decode_burst_seconds
                    or self._generation_steps >= self.decode_burst_steps):
                self.reset()
