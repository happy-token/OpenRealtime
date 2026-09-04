"""Long-lived recovery and Transactional Outbox dispatch runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from server.agent_session.driver_protocol import utc_now


logger = logging.getLogger(__name__)


class _Supervisor(Protocol):
    async def recover_active(self) -> tuple[str, ...]: ...

    async def dispatch_once(
        self,
        *,
        owner: str,
        limit: int,
        lease_seconds: float,
        retry_delay_seconds: float,
    ) -> tuple[Any, ...]: ...

    async def shutdown(self) -> None: ...


def _runtime_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


@dataclass(frozen=True, slots=True)
class SupervisorRuntimeConfig:
    owner: str = field(default_factory=_runtime_owner)
    batch_size: int = 10
    lease_seconds: float = 30.0
    retry_delay_seconds: float = 1.0
    poll_interval_seconds: float = 0.05
    error_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("runtime owner must be non-empty")
        if self.batch_size < 1:
            raise ValueError("runtime batch_size must be positive")
        for value in (
            self.lease_seconds,
            self.retry_delay_seconds,
            self.poll_interval_seconds,
            self.error_backoff_seconds,
        ):
            if value < 0:
                raise ValueError("runtime durations must be non-negative")
        if self.lease_seconds == 0:
            raise ValueError("runtime lease_seconds must be positive")


@dataclass(frozen=True, slots=True)
class SupervisorRuntimeSnapshot:
    running: bool
    recovered_workers: tuple[str, ...]
    dispatch_cycles: int
    dispatched_messages: int
    consecutive_errors: int
    last_error: str | None
    started_at: datetime | None


class AgentSupervisorRuntime:
    """Owns one Supervisor's recovery, dispatch loop, and orderly shutdown."""

    def __init__(
        self,
        supervisor: _Supervisor,
        *,
        config: SupervisorRuntimeConfig | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._config = config or SupervisorRuntimeConfig()
        self._lifecycle_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._closed = False
        self._running = False
        self._recovered_workers: tuple[str, ...] = ()
        self._dispatch_cycles = 0
        self._dispatched_messages = 0
        self._consecutive_errors = 0
        self._last_error: str | None = None
        self._started_at: datetime | None = None

    @property
    def snapshot(self) -> SupervisorRuntimeSnapshot:
        return SupervisorRuntimeSnapshot(
            running=self._running,
            recovered_workers=self._recovered_workers,
            dispatch_cycles=self._dispatch_cycles,
            dispatched_messages=self._dispatched_messages,
            consecutive_errors=self._consecutive_errors,
            last_error=self._last_error,
            started_at=self._started_at,
        )

    async def start(self) -> tuple[str, ...]:
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("AgentSupervisorRuntime is closed")
            if self._loop_task is not None:
                return self._recovered_workers
            self._recovered_workers = await self._supervisor.recover_active()
            self._started_at = utc_now()
            self._running = True
            self._loop_task = asyncio.create_task(
                self._dispatch_loop(),
                name=f"agent-supervisor-runtime-{self._config.owner}",
            )
            return self._recovered_workers

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            loop_task = self._loop_task
            if loop_task is not None:
                loop_task.cancel()
        if loop_task is not None:
            await asyncio.gather(loop_task, return_exceptions=True)
        try:
            await self._supervisor.shutdown()
        finally:
            self._running = False

    async def __aenter__(self) -> AgentSupervisorRuntime:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info
        await self.close()

    async def _dispatch_loop(self) -> None:
        try:
            while not self._stop.is_set():
                delay = self._config.poll_interval_seconds
                try:
                    results = await self._supervisor.dispatch_once(
                        owner=self._config.owner,
                        limit=self._config.batch_size,
                        lease_seconds=self._config.lease_seconds,
                        retry_delay_seconds=self._config.retry_delay_seconds,
                    )
                    self._dispatch_cycles += 1
                    self._dispatched_messages += len(results)
                    self._consecutive_errors = 0
                    if results:
                        delay = 0
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._consecutive_errors += 1
                    self._last_error = f"{type(error).__name__}: {error}"
                    delay = self._config.error_backoff_seconds
                    logger.exception("Agent Supervisor dispatch cycle failed")
                await self._wait_or_stop(delay)
        finally:
            self._running = False

    async def _wait_or_stop(self, delay: float) -> None:
        if delay <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            pass
