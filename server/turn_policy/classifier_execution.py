"""Provider-neutral classifier deadlines and task-local stage diagnostics."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from server.observability.telemetry import SessionTelemetry, TelemetryKind, TelemetryOutcome

StageObserver = Callable[[str, float, str], None]
CapacityWaitObserver = Callable[[float, str], None]
CLASSIFIER_STAGE_OBSERVER: ContextVar[StageObserver | None] = ContextVar("classifier_stage_observer", default=None)
logger = logging.getLogger(__name__)


class ClassificationCapacityError(RuntimeError):
    """Unfinished calls, including cancelled plugins, occupy all execution slots."""


class ClassificationExecutor:
    """Bound waiting without trusting a plugin to cooperate with cancellation.

    The owning conversation closes this executor. A cancelled plugin that continues
    running stays tracked and occupies a slot until it actually finishes; exhausting
    those slots rejects new work instead of accumulating detached provider tasks.
    This bounds caller waiting and task count, not CPU-blocking plugin execution.
    """

    def __init__(self, max_pending: int) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("classifier execution capacity must be a positive integer")
        self._max_pending = max_pending
        self._pending: set[asyncio.Task[Any]] = set()
        self._abandoned: set[asyncio.Task[Any]] = set()
        self._owners: dict[asyncio.Task[Any], asyncio.Task[Any] | None] = {}
        self._closed = False

    @property
    def pending_count(self) -> int:
        return sum(not task.done() for task in self._pending)

    def _check_capacity(self) -> None:
        if self._closed:
            raise RuntimeError("classifier executor is closed")
        if self.pending_count >= self._max_pending:
            raise ClassificationCapacityError("classifier execution capacity exhausted")

    def _finished(self, task: asyncio.Task[Any]) -> None:
        abandoned = task in self._abandoned
        self._pending.discard(task)
        self._abandoned.discard(task)
        self._owners.pop(task, None)
        if not task.cancelled():
            error = task.exception()  # Retrieve even an abandoned provider's failure.
            if abandoned and error is not None:
                logger.warning("Discarded classifier failed after cancellation: %s", type(error).__name__)

    def _cancel(self, task: asyncio.Task[Any]) -> None:
        if not task.done():
            self._abandoned.add(task)
            task.cancel()

    @staticmethod
    def _deadline(timeout_s: float) -> float:
        if not math.isfinite(timeout_s) or timeout_s < 0:
            raise ValueError("classifier deadline must be finite and non-negative")
        return asyncio.get_running_loop().time() + timeout_s

    def _cancelling_tasks(self) -> tuple[asyncio.Task[Any], ...]:
        return tuple(task for task in self._pending if not task.done() and (
            task in self._abandoned or task.cancelling()
            or ((owner := self._owners.get(task)) is not None and owner.cancelling())
        ))

    async def _wait_for_capacity(
        self, deadline: float, observe: CapacityWaitObserver | None = None,
    ) -> None:
        try:
            self._check_capacity()
            return
        except ClassificationCapacityError:
            if not self._cancelling_tasks():
                raise

        # A rewrite's replacement can reach admission before the cancelled child
        # runs its finally block. Give only that cancellation handoff a bounded
        # grace period; active requests never acquire an unbounded waiting queue.
        loop = asyncio.get_running_loop()
        started = loop.time()
        cleanup_deadline = min(deadline, started + 0.05)
        outcome = "ok"
        try:
            await asyncio.sleep(0)
            while self.pending_count >= self._max_pending and not self._closed:
                candidates = self._cancelling_tasks()
                remaining = cleanup_deadline - loop.time()
                if not candidates or remaining <= 0:
                    break
                await asyncio.wait(candidates, timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED)
            self._check_capacity()
        except ClassificationCapacityError:
            outcome = "timeout"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            if observe is not None:
                observe((loop.time() - started) * 1000, outcome)

    async def _run_until[T](self, invoke: Callable[[], Awaitable[T]], deadline: float) -> T:
        self._check_capacity()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("classifier execution deadline exceeded")

        async def execute() -> T:
            return await invoke()

        task = asyncio.create_task(execute(), name="semantic-classifier")
        self._pending.add(task)
        self._owners[task] = asyncio.current_task()
        task.add_done_callback(self._finished)
        try:
            done, _ = await asyncio.wait((task,), timeout=remaining)
            if not done:
                self._cancel(task)
                raise TimeoutError("classifier execution deadline exceeded")
            if self._closed or task in self._abandoned:
                raise asyncio.CancelledError
            return task.result()
        except asyncio.CancelledError:
            if task not in self._abandoned:
                self._cancel(task)
            raise
        finally:
            self._owners.pop(task, None)  # Cleanup must not cancel the caller's later work.

    async def run[T](self, invoke: Callable[[], Awaitable[T]], timeout_s: float) -> T:
        deadline = self._deadline(timeout_s)
        await self._wait_for_capacity(deadline)
        return await self._run_until(invoke, deadline)

    async def close(self, timeout_s: float = 0.1) -> int:
        """Reject new calls, request cancellation, and report unfinished cleanup."""
        if not math.isfinite(timeout_s) or timeout_s < 0:
            raise ValueError("classifier cleanup deadline must be finite and non-negative")
        self._closed = True
        tasks = tuple(task for task in self._pending if not task.done())
        for task in tasks:
            self._cancel(task)
            owner = self._owners.get(task)
            if owner is not None and owner is not asyncio.current_task():
                owner.cancel()  # Do not leave callers waiting on quarantined plugins.
        if tasks:
            await asyncio.wait(tasks, timeout=timeout_s)
        return self.pending_count


@contextmanager
def classification_stage(provider: str, stage: str) -> Iterator[None]:
    started = time.monotonic_ns()
    outcome = "ok"
    try:
        yield
    except TimeoutError:
        outcome = "timeout"
        raise
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        observer = CLASSIFIER_STAGE_OBSERVER.get()
        if observer is not None:
            observer(f"{provider}.{stage}", (time.monotonic_ns() - started) / 1_000_000, outcome)


async def run_classification[T](
    invoke: Callable[[], Awaitable[T]], *, operation: str, timeout_s: float,
    telemetry: SessionTelemetry | None, generation: int, attributes: dict[str, object],
    executor: ClassificationExecutor,
) -> T:
    deadline = executor._deadline(timeout_s)

    def observe_capacity_wait(duration_ms: float, outcome: str) -> None:
        if telemetry is not None:
            telemetry.record(f"turn_policy.{operation}_capacity_wait", generation=generation,
                kind=TelemetryKind.SPAN, duration_ms=duration_ms,
                outcome=TelemetryOutcome(outcome),
                attributes={**attributes, "operation": operation})

    try:
        await executor._wait_for_capacity(deadline, observe_capacity_wait)
    except ClassificationCapacityError:
        if telemetry is not None:
            telemetry.record("turn_policy.classification_rejected", generation=generation,
                outcome=TelemetryOutcome.ERROR,
                attributes={**attributes, "operation": operation, "reason": "capacity",
                    "pending_count": executor.pending_count})
        raise

    active = True
    previous_observer = CLASSIFIER_STAGE_OBSERVER.get()

    def observe_stage(name: str, duration_ms: float, outcome: str) -> None:
        if not active or executor._closed:
            return  # A quarantined provider's late stages cannot report success.
        if telemetry is None:
            if previous_observer is not None:
                previous_observer(name, duration_ms, outcome)
            return
        provider, stage = name.split(".", 1)
        telemetry.record(f"{provider}.{operation}.{stage}", generation=generation,
            kind=TelemetryKind.SPAN, duration_ms=duration_ms,
            outcome=TelemetryOutcome(outcome), attributes=attributes)

    token = CLASSIFIER_STAGE_OBSERVER.set(observe_stage)
    try:
        if telemetry is None:
            return await executor._run_until(invoke, deadline)
        call_attributes = {**attributes, "effective_timeout_ms":
            max(0, (deadline - asyncio.get_running_loop().time()) * 1000)}
        async with telemetry.provider_call(provider=f"{operation}_classifier", operation="classify",
            timeout_ms=timeout_s * 1000, generation=generation, attributes=call_attributes) as call:
            result = await executor._run_until(invoke, deadline)
            call.mark_first_response()
            return result
    finally:
        active = False
        CLASSIFIER_STAGE_OBSERVER.reset(token)
