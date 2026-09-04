"""Deterministic Agent Driver Protocol conformer for tests and demos."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentDriver,
    AgentEvent,
    AgentEventBase,
    AgentInput,
    AgentMessageDelta,
    AgentProgressUpdated,
    AgentRunHandle,
    AgentRunLocator,
    AgentRunPhase,
    AgentRunSnapshot,
    AgentRunStarted,
    AgentRunTerminal,
    AgentRunWaiting,
    AgentStartRequest,
    CancelResult,
    utc_now,
)


@dataclass(slots=True)
class _Run:
    handle: AgentRunHandle
    phase: AgentRunPhase = AgentRunPhase.RUNNING
    events: list[AgentEvent] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    inputs: list[AgentInput] = field(default_factory=list)


class InMemoryAgentDriverV2(AgentDriver):
    def __init__(self, *, driver_kind: str = "in-memory") -> None:
        self._descriptor = AgentCapabilityDescriptor(
            driver_kind=driver_kind,
            driver_version="0.1.0",
            protocol_version="2",
            capabilities=frozenset(AgentCapability),
        )
        self._runs_by_worker: dict[str, _Run] = {}
        self._runs_by_dispatch: dict[str, _Run] = {}
        self._runs_by_session: dict[str, _Run] = {}
        self._lock = asyncio.Lock()
        self.start_count = 0

    async def capabilities(self) -> AgentCapabilityDescriptor:
        return self._descriptor

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        async with self._lock:
            existing = self._runs_by_dispatch.get(request.dispatch_token)
            if existing is not None:
                if existing.handle.worker_id != request.worker_id:
                    raise ValueError("dispatch token already belongs to another worker")
                return existing.handle

            self.start_count += 1
            locator = AgentRunLocator(
                driver_kind=self._descriptor.driver_kind,
                backend_session_id=f"session-{request.worker_id}",
                backend_run_id=f"run-{request.worker_id}",
            )
            handle = AgentRunHandle(
                worker_id=request.worker_id,
                dispatch_token=request.dispatch_token,
                locator=locator,
                capabilities=self._descriptor,
            )
            run = _Run(handle=handle)
            self._runs_by_worker[request.worker_id] = run
            self._runs_by_dispatch[request.dispatch_token] = run
            self._runs_by_session[locator.backend_session_id] = run
            self._append_locked(run, AgentRunStarted, {})
            return handle

    async def resume(
        self,
        locator: AgentRunLocator,
        *,
        worker_id: str,
        dispatch_token: str,
        after_sequence: int,
    ) -> AgentRunHandle:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        async with self._lock:
            run = self._runs_by_session.get(locator.backend_session_id)
            if (
                run is None
                or run.handle.worker_id != worker_id
                or run.handle.dispatch_token != dispatch_token
                or after_sequence > len(run.events)
            ):
                raise KeyError(locator.backend_session_id)
            return run.handle

    async def status(self, handle: AgentRunHandle) -> AgentRunSnapshot:
        run = self._get(handle)
        return AgentRunSnapshot(
            worker_id=handle.worker_id,
            phase=run.phase,
            locator=handle.locator,
            last_event_sequence=len(run.events),
            result=run.result,
            error=run.error,
        )

    async def events(self, handle: AgentRunHandle, *, after: int | None = None):
        run = self._get(handle)
        cursor = after or 0
        while True:
            async with run.condition:
                await run.condition.wait_for(
                    lambda cursor=cursor: len(run.events) > cursor or run.phase.terminal
                )
                pending = tuple(run.events[cursor:])
            for event in pending:
                cursor = event.sequence
                yield event
                if isinstance(event, AgentRunTerminal):
                    return
            if run.phase.terminal and cursor >= len(run.events):
                return

    async def send_input(self, handle: AgentRunHandle, input: AgentInput) -> None:
        run = self._get(handle)
        if run.phase.terminal:
            raise RuntimeError("cannot send input to a terminal Agent run")
        run.inputs.append(input)

    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult:
        run = self._get(handle)
        if run.phase.terminal:
            return CancelResult(
                requested=False,
                stopped=run.phase is AgentRunPhase.CANCELLED,
                phase=run.phase,
            )
        await self._terminal(run, AgentRunPhase.CANCELLED, error=reason)
        return CancelResult(requested=True, stopped=True, phase=AgentRunPhase.CANCELLED)

    async def close(self, handle: AgentRunHandle) -> None:
        self._get(handle)

    async def progress(self, worker_id: str, text: str, *, version: int) -> None:
        run = self._runs_by_worker[worker_id]
        async with self._lock:
            self._append_locked(
                run,
                AgentProgressUpdated,
                {"text": text, "progress_version": version},
            )
        await self._notify(run)

    async def message(self, worker_id: str, text: str) -> None:
        run = self._runs_by_worker[worker_id]
        async with self._lock:
            self._append_locked(run, AgentMessageDelta, {"text": text})
        await self._notify(run)

    async def wait_for_input(self, worker_id: str, reason: str) -> None:
        run = self._runs_by_worker[worker_id]
        async with self._lock:
            run.phase = AgentRunPhase.WAITING
            self._append_locked(run, AgentRunWaiting, {"reason": reason})
        await self._notify(run)

    async def complete(self, worker_id: str, result: str) -> None:
        await self._terminal(
            self._runs_by_worker[worker_id], AgentRunPhase.SUCCEEDED, result=result
        )

    async def fail(self, worker_id: str, error: str) -> None:
        await self._terminal(self._runs_by_worker[worker_id], AgentRunPhase.FAILED, error=error)

    async def _terminal(
        self,
        run: _Run,
        phase: AgentRunPhase,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            if run.phase.terminal:
                return
            run.phase = phase
            run.result = result
            run.error = error
            self._append_locked(
                run,
                AgentRunTerminal,
                {"phase": phase, "result": result, "error": error},
            )
        await self._notify(run)

    def _append_locked(
        self,
        run: _Run,
        event_type: type[AgentEventBase],
        values: dict[str, object],
    ) -> None:
        event = event_type(
            worker_id=run.handle.worker_id,
            event_id=str(uuid.uuid4()),
            sequence=len(run.events) + 1,
            occurred_at=utc_now(),
            locator=run.handle.locator,
            **values,
        )
        run.events.append(event)

    async def _notify(self, run: _Run) -> None:
        async with run.condition:
            run.condition.notify_all()

    def _get(self, handle: AgentRunHandle) -> _Run:
        run = self._runs_by_worker.get(handle.worker_id)
        if run is None or run.handle != handle:
            raise KeyError(handle.worker_id)
        return run
