from __future__ import annotations

from dataclasses import dataclass, field

from freetoken.engine import EngineConfig

from .policy import FairBatchPolicy


def _get_pid_suffix() -> str:
    import os

    return f".pid={os.getpid()}"


@dataclass(frozen=True)
class SchedulerConfig(EngineConfig):
    max_extend_tokens: int = 8192
    scheduler_policy: str = "prefill-first"
    scheduler_decode_burst_ms: float = 200.0
    scheduler_decode_burst_steps: int = 8
    cache_type: str = "radix"
    offline_mode: bool = False
    decode_log_interval: int = 40
    special_token_ckpt: bool = False
    # --prefix-disk-cache DIR: keep hybrid prefix-cache entries (KV pages + GDN snapshot) on
    # disk, written while idle and read back at admission when they reach deeper than the tree
    # (scheduler/prefix_disk.py). None = off. --prefix-disk-cache-size caps the directory.
    prefix_disk_cache: str | None = None
    prefix_disk_cache_size: str = "32G"

    # networking config
    _unique_suffix: str = field(default_factory=_get_pid_suffix)

    def __post_init__(self):
        super().__post_init__()
        if self.scheduler_policy not in ("prefill-first", "fair"):
            raise ValueError("scheduler_policy must be 'prefill-first' or 'fair'")
        if self.scheduler_policy == "fair" and self.tp_info.size != 1:
            raise ValueError("the fair scheduler policy requires a single rank")
        FairBatchPolicy(self.scheduler_decode_burst_ms, self.scheduler_decode_burst_steps)

    @property
    def zmq_backend_addr(self) -> str:
        return "ipc:///tmp/freetoken_0" + self._unique_suffix

    @property
    def zmq_detokenizer_addr(self) -> str:
        return "ipc:///tmp/freetoken_1" + self._unique_suffix

    @property
    def zmq_scheduler_broadcast_addr(self) -> str:
        return "ipc:///tmp/freetoken_2" + self._unique_suffix

    @property
    def max_forward_len(self) -> int:
        return self.max_extend_tokens

    @property
    def backend_create_detokenizer_link(self) -> bool:
        return True
