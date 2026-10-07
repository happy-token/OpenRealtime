"""Output-only cache budgets and retained ownership of retired producers.

Input and conversation context are never truncated. Candidate residency ends
at formal claim; the formal response keeps its existing Core deadlines. Live
consumers drain bounded buffers with backpressure instead of restarting output.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field

from server.core.async_stream import OwnedStreamCleanupError


@dataclass(frozen=True, slots=True)
class SpeculativeOutputBudget:
    text_bytes: int = 64 * 1024
    text_chunks: int = 1024
    audio_bytes: int = 8 * 1024 * 1024
    audio_chunks: int = 2048
    audio_seconds: float = 30.0
    candidate_seconds: float = 30.0

    def __post_init__(self) -> None:
        for value in (self.text_bytes, self.text_chunks, self.audio_bytes, self.audio_chunks):
            if value <= 0:
                raise ValueError("speculative byte/chunk budgets must be positive")
        for duration in (self.audio_seconds, self.candidate_seconds):
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("speculative time budgets must be finite and positive")


class SpeculativeBudgetExceeded(RuntimeError):
    """An uncommitted candidate or single supplier packet exceeded its budget."""


@dataclass(slots=True)
class SpeculativeState:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    started_ns: int = field(default_factory=time.monotonic_ns)
    task: asyncio.Task[None] | None = None
    done: bool = False
    invalidated: bool = False
    claimed: bool = False
    cleanup_started: bool = False
    expiry_handle: asyncio.TimerHandle | None = None
    error: Exception | None = None
    cleanup_error: Exception | None = None
    retired: asyncio.Event = field(default_factory=asyncio.Event)

    def claim(self, budget: SpeculativeOutputBudget) -> bool:
        # Called while the cache admission lock is held, with no await.
        expired = (time.monotonic_ns() - self.started_ns) / 1e9 >= budget.candidate_seconds
        if not self.claimed and expired and self.error is None:
            self.error = SpeculativeBudgetExceeded("candidate_residency")
        if isinstance(self.error, SpeculativeBudgetExceeded):
            return False
        if self.retired.is_set() and not self.done:
            raise OwnedStreamCleanupError("retired speculative candidate cleanup remains pending")
        self.claimed = True
        if self.expiry_handle is not None:
            self.expiry_handle.cancel()
            self.expiry_handle = None
        return True


class SpeculativeBuffer[T]:
    """Only cache-owned payloads; one supplier packet may be in flight outside it."""

    def __init__(self, *, state: SpeculativeState, byte_limit: int, chunk_limit: int,
                 measure: Callable[[T], tuple[int, float]], seconds_limit: float = math.inf) -> None:
        self._state = state
        self._byte_limit = byte_limit
        self._chunk_limit = chunk_limit
        self._seconds_limit = seconds_limit
        self._measure = measure
        self._entries: deque[tuple[T, int, float]] = deque()
        self.bytes = 0
        self.seconds = 0.0

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[T]:
        return (entry[0] for entry in self._entries)

    async def append(self, item: T) -> bool:
        if not self._state.claimed and isinstance(self._state.error, SpeculativeBudgetExceeded):
            raise SpeculativeBudgetExceeded(str(self._state.error))
        size, seconds = self._measure(item)
        if size > self._byte_limit or seconds > self._seconds_limit:
            raise SpeculativeBudgetExceeded("supplier_packet")
        async with self._state.condition:
            while (self.bytes + size > self._byte_limit or len(self) >= self._chunk_limit
                   or self.seconds + seconds > self._seconds_limit):
                if self._state.invalidated:
                    return False
                if not self._state.claimed:
                    raise SpeculativeBudgetExceeded("candidate_buffer")
                await self._state.condition.wait()
            if self._state.invalidated:
                return False
            self._entries.append((item, size, seconds))
            self.bytes += size
            self.seconds += seconds
            self._state.condition.notify_all()
        return True

    def pop(self) -> T:
        # The caller owns state.condition, releasing producer backpressure.
        item, size, seconds = self._entries.popleft()
        self.bytes -= size
        self.seconds = max(0.0, self.seconds - seconds)
        self._state.condition.notify_all()
        return item

    def clear(self) -> None:
        self._entries.clear()
        self.bytes = 0
        self.seconds = 0.0


def text_cost(text: str, limit: int) -> tuple[int, float]:
    # Check character count before allocating a potentially enormous encoding.
    if len(text) > limit:
        raise SpeculativeBudgetExceeded("supplier_packet")
    return len(text.encode("utf-8")), 0.0


class SpeculativeCleanupOwner:
    """Keep actual producers after waiter cancellation; quarantine failed cleanup."""

    def __init__(self) -> None:
        self._retired: dict[asyncio.Task[None], SpeculativeState] = {}
        self._failure: Exception | None = None

    async def discard(self, state: SpeculativeState, *, confirmed: bool) -> None:
        state.invalidated = True
        state.retired.set()
        if state.expiry_handle is not None:
            state.expiry_handle.cancel()
            state.expiry_handle = None
        async with state.condition:
            state.condition.notify_all()
        task = state.task
        if task is None:
            return
        if task not in self._retired:
            self._retired[task] = state
            task.add_done_callback(self._finished)
        if state.claimed and not task.done() and not task.cancelling() and not state.cleanup_started:
            task.cancel()
        if confirmed:
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        else:
            await asyncio.wait({task}, timeout=.1)
        self._check_finished()
        self._raise_failure()

    async def close(self) -> None:
        self._check_finished()
        while self._retired:
            await asyncio.shield(asyncio.gather(*tuple(self._retired), return_exceptions=True))
            self._check_finished()
        self._raise_failure()

    def record_failure(self, error: Exception) -> None:
        # Never retain provider frames or oversized rejected packets through a cause.
        self._failure = OwnedStreamCleanupError(str(error)[:2048])

    async def admit(self) -> None:
        self._check_finished()
        self._raise_failure()
        if self._retired:
            # A bounded admission wait does not declare the old supplier released.
            await asyncio.wait(set(self._retired), timeout=.1)
            self._check_finished()
            self._raise_failure()
            if self._retired:
                raise OwnedStreamCleanupError("speculative provider cleanup remains pending")

    def _finished(self, task: asyncio.Task[None]) -> None:
        state = self._retired.pop(task, None)
        if state is not None and state.cleanup_error is not None:
            self.record_failure(state.cleanup_error)
        if not task.cancelled():
            task.exception()

    def _check_finished(self) -> None:
        for task in tuple(self._retired):
            if task.done():
                self._finished(task)

    def _raise_failure(self) -> None:
        if self._failure is not None:
            raise OwnedStreamCleanupError(f"speculative provider cleanup failed: {self._failure}") from self._failure


async def join_owned_tasks(tasks: set[asyncio.Task[None]]) -> list[object]:
    """Repeated cancellation of the outer owner cannot re-cancel supplier finally."""
    joined = asyncio.gather(*tasks, return_exceptions=True)
    while True:
        try:
            return list(await asyncio.shield(joined))
        except asyncio.CancelledError:
            if joined.done():
                return list(joined.result())
            # The caller remains the retained owner until actual cleanup completes.
            continue


def detached_error(error: Exception) -> Exception:
    """Stored terminal diagnostics must not own provider packet traceback frames."""
    message = str(error)[:2048]
    for kind in (SpeculativeBudgetExceeded, OwnedStreamCleanupError, TimeoutError,
                 ValueError, TypeError, RuntimeError):
        if isinstance(error, kind):
            return kind(message)
    return RuntimeError(f"{type(error).__name__}: {message}")


async def candidate_queue_operation[T](operation: Callable[[], Awaitable[T]],
                                      state: SpeculativeState) -> T | None:
    """Cancel only an internal queue wait, never a supplier's active __anext__."""
    if state.retired.is_set():
        return None
    pending = asyncio.ensure_future(operation())
    retired = asyncio.create_task(state.retired.wait())
    try:
        done, _ = await asyncio.wait({pending, retired}, return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            return pending.result()
        return None
    finally:
        for task in (pending, retired):
            if not task.done():
                task.cancel()
        await asyncio.gather(pending, retired, return_exceptions=True)
