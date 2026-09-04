"""Universal Agent Driver adapter for an ACP-compatible Hermes process.

The legacy ACP transport is process-local and cannot prove durable resume or
idempotent start, so this adapter deliberately omits those capabilities.
AgentTaskSupervisor remains the only component allowed to start a run.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentEvent,
    AgentInput,
    AgentMessageDelta,
    AgentRunHandle,
    AgentRunLocator,
    AgentRunPhase,
    AgentRunSnapshot,
    AgentRunStarted,
    AgentRunTerminal,
    AgentStartRequest,
    CancelResult,
    utc_now,
)
from server.agent_session.plugins.acp_driver import AcpAgentSession, AcpDriver
from server.core.turn_content import TurnContent


@dataclass(slots=True)
class _HermesRun:
    handle: AgentRunHandle
    session: AcpAgentSession
    phase: AgentRunPhase = AgentRunPhase.STARTING
    events: list[AgentEvent] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    monitor: asyncio.Task[None] | None = None


class HermesAcpDriver:
    """Expose an ACP session through the universal v2 Agent Driver API."""

    def __init__(
        self,
        *,
        acp: AcpDriver | None = None,
        poll_interval_seconds: float = 0.02,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._acp = acp or AcpDriver(command=("hermes", "acp"))
        self._poll_interval_seconds = poll_interval_seconds
        self._runs: dict[str, _HermesRun] = {}
        self._closed_workers: set[str] = set()

    async def capabilities(self) -> AgentCapabilityDescriptor:
        return AgentCapabilityDescriptor(
            driver_kind="hermes_acp",
            driver_version="1",
            protocol_version="agent-driver-v2",
            capabilities=frozenset(
                {
                    AgentCapability.STATUS_LOOKUP,
                    AgentCapability.EVENT_STREAM,
                    AgentCapability.CANCEL,
                }
            ),
        )

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        if request.worker_id in self._runs:
            raise RuntimeError("Hermes ACP start is not idempotent")
        locator = AgentRunLocator(
            driver_kind="hermes_acp",
            backend_session_id=str(uuid.uuid4()),
        )
        handle = AgentRunHandle(
            worker_id=request.worker_id,
            dispatch_token=request.dispatch_token,
            locator=locator,
            capabilities=await self.capabilities(),
        )
        run = _HermesRun(handle=handle, session=self._acp.create_session())
        self._runs[request.worker_id] = run
        await self._append(
            run,
            AgentRunStarted(
                worker_id=request.worker_id,
                event_id=str(uuid.uuid4()),
                sequence=1,
                occurred_at=utc_now(),
                locator=locator,
            ),
        )
        run.phase = AgentRunPhase.RUNNING
        await run.session.send_turn(
            TurnContent(text=request.instruction, generation=request.context.generation)
        )
        run.monitor = asyncio.create_task(
            self._monitor(run), name=f"hermes-acp-{request.worker_id}"
        )
        return handle

    async def resume(
        self,
        locator: AgentRunLocator,
        *,
        worker_id: str,
        dispatch_token: str,
        after_sequence: int,
    ) -> AgentRunHandle:
        raise NotImplementedError("Hermes ACP cannot durably resume a prior process")

    async def status(self, handle: AgentRunHandle) -> AgentRunSnapshot:
        run = self._require(handle)
        return AgentRunSnapshot(
            worker_id=handle.worker_id,
            phase=run.phase,
            locator=handle.locator,
            last_event_sequence=len(run.events),
            result=run.result,
            error=run.error,
        )

    async def events(
        self, handle: AgentRunHandle, *, after: int | None = None
    ) -> AsyncIterator[AgentEvent]:
        run = self._require(handle)
        cursor = after or 0
        if cursor < 0 or cursor > len(run.events):
            raise ValueError("Agent event cursor is outside the retained event history")
        while True:
            async with run.condition:
                await run.condition.wait_for(
                    lambda cursor=cursor: len(run.events) > cursor or run.phase.terminal
                )
                pending = tuple(run.events[cursor:])
            for event in pending:
                cursor = event.sequence
                yield event
            if run.phase.terminal and cursor >= len(run.events):
                return

    async def send_input(self, handle: AgentRunHandle, input: AgentInput) -> None:
        raise NotImplementedError("Hermes ACP steering is not implemented")

    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult:
        run = self._require(handle)
        if run.phase.terminal:
            return CancelResult(requested=False, stopped=True, phase=run.phase)
        run.phase = AgentRunPhase.CANCELLING
        await run.session.cancel()
        await self._terminal(run, AgentRunPhase.CANCELLED, error=reason)
        return CancelResult(
            requested=True, stopped=True, phase=AgentRunPhase.CANCELLED
        )

    async def close(self, handle: AgentRunHandle) -> None:
        run = self._require(handle)
        if run.monitor is not None and not run.monitor.done():
            run.monitor.cancel()
            await asyncio.gather(run.monitor, return_exceptions=True)
        self._closed_workers.add(handle.worker_id)
        if self._closed_workers == self._runs.keys():
            await self._acp.close()

    async def _monitor(self, run: _HermesRun) -> None:
        emitted_text = ""
        result_task = asyncio.create_task(run.session.result())
        try:
            while not result_task.done():
                update = await run.session.latest_update()
                current = update.text if update is not None else ""
                if current.startswith(emitted_text) and len(current) > len(emitted_text):
                    delta = current[len(emitted_text) :]
                    emitted_text = current
                    await self._message_delta(run, delta)
                await asyncio.sleep(self._poll_interval_seconds)
            outcome = await result_task
            update = await run.session.latest_update()
            current = update.text if update is not None else ""
            if current.startswith(emitted_text) and len(current) > len(emitted_text):
                await self._message_delta(run, current[len(emitted_text) :])
            if run.phase.terminal:
                return
            if outcome.ok:
                await self._terminal(
                    run, AgentRunPhase.SUCCEEDED, result=outcome.text or ""
                )
            else:
                await self._terminal(
                    run,
                    AgentRunPhase.FAILED,
                    error=outcome.error or "Hermes ACP run failed",
                )
        except asyncio.CancelledError:
            result_task.cancel()
            raise
        except Exception as error:
            if not run.phase.terminal:
                await self._terminal(
                    run,
                    AgentRunPhase.FAILED,
                    error=f"{type(error).__name__}: {error}",
                )

    async def _message_delta(self, run: _HermesRun, text: str) -> None:
        await self._append(
            run,
            AgentMessageDelta(
                worker_id=run.handle.worker_id,
                event_id=str(uuid.uuid4()),
                sequence=len(run.events) + 1,
                occurred_at=utc_now(),
                locator=run.handle.locator,
                text=text,
            ),
        )

    async def _terminal(
        self,
        run: _HermesRun,
        phase: AgentRunPhase,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        if run.phase.terminal:
            return
        run.phase = phase
        run.result = result
        run.error = error
        await self._append(
            run,
            AgentRunTerminal(
                worker_id=run.handle.worker_id,
                event_id=str(uuid.uuid4()),
                sequence=len(run.events) + 1,
                occurred_at=utc_now(),
                locator=run.handle.locator,
                phase=phase,
                result=result,
                error=error,
            ),
        )

    async def _append(self, run: _HermesRun, event: AgentEvent) -> None:
        async with run.condition:
            run.events.append(event)
            run.condition.notify_all()

    def _require(self, handle: AgentRunHandle) -> _HermesRun:
        run = self._runs.get(handle.worker_id)
        if run is None or run.handle != handle:
            raise KeyError(f"unknown Hermes ACP handle for {handle.worker_id!r}")
        return run
