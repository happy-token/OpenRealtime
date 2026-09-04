"""Claude Code stream-json adapter for the universal v2 Agent Driver API."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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
    AgentUsageUpdated,
    CancelResult,
    utc_now,
)


@dataclass(slots=True)
class _ClaudeRun:
    handle: AgentRunHandle
    process: asyncio.subprocess.Process
    phase: AgentRunPhase = AgentRunPhase.RUNNING
    events: list[AgentEvent] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    reader: asyncio.Task[None] | None = None


class ClaudeStreamJsonDriver:
    """Run one exact Claude CLI process per supervised worker.

    The CLI stream is replayable only while this Python process is alive;
    durable resume and idempotent start are therefore intentionally omitted.
    """

    def __init__(
        self,
        command: Sequence[str] = ("claude",),
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("Claude command must be non-empty")
        self._command = tuple(command)
        self._env = {**os.environ, **env} if env is not None else None
        self._runs: dict[str, _ClaudeRun] = {}

    async def capabilities(self) -> AgentCapabilityDescriptor:
        return AgentCapabilityDescriptor(
            driver_kind="claude_stream_json",
            driver_version="1",
            protocol_version="agent-driver-v2",
            capabilities=frozenset(
                {
                    AgentCapability.STATUS_LOOKUP,
                    AgentCapability.EVENT_STREAM,
                    AgentCapability.CANCEL,
                    AgentCapability.STRUCTURED_RESULT,
                    AgentCapability.USAGE_REPORTING,
                }
            ),
        )

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        if request.worker_id in self._runs:
            raise RuntimeError("Claude stream-json start is not idempotent")
        session_id = str(uuid.uuid4())
        locator = AgentRunLocator(
            driver_kind="claude_stream_json",
            backend_session_id=session_id,
        )
        handle = AgentRunHandle(
            worker_id=request.worker_id,
            dispatch_token=request.dispatch_token,
            locator=locator,
            capabilities=await self.capabilities(),
        )
        command = [
            *self._command,
            "-p",
            request.instruction,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--session-id",
            session_id,
            "--permission-mode",
            "dontAsk",
        ]
        if request.model:
            command.extend(("--model", request.model))
        max_turns = request.budget.get("max_turns")
        if isinstance(max_turns, int) and max_turns > 0:
            command.extend(("--max-turns", str(max_turns)))
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=request.workspace.root,
            env=self._env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        run = _ClaudeRun(handle=handle, process=process)
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
        run.reader = asyncio.create_task(
            self._read_stream(run), name=f"claude-stream-{request.worker_id}"
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
        raise NotImplementedError(
            "Claude stream-json cannot durably resume an unowned CLI process"
        )

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
        raise NotImplementedError("Claude stream-json steering is not implemented")

    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult:
        run = self._require(handle)
        if run.phase.terminal:
            return CancelResult(requested=False, stopped=True, phase=run.phase)
        run.phase = AgentRunPhase.CANCELLING
        if run.process.returncode is None:
            run.process.terminate()
            try:
                await asyncio.wait_for(run.process.wait(), timeout=2)
            except TimeoutError:
                run.process.kill()
                await run.process.wait()
        await self._terminal(run, AgentRunPhase.CANCELLED, error=reason)
        return CancelResult(
            requested=True, stopped=True, phase=AgentRunPhase.CANCELLED
        )

    async def close(self, handle: AgentRunHandle) -> None:
        run = self._require(handle)
        if not run.phase.terminal:
            await self.cancel(handle, "driver closed")
        if run.reader is not None and not run.reader.done():
            await asyncio.gather(run.reader, return_exceptions=True)
        if run.process.returncode is None:
            try:
                await asyncio.wait_for(run.process.wait(), timeout=2)
            except TimeoutError:
                run.process.terminate()
                await run.process.wait()
        await self._stderr(run)

    async def _read_stream(self, run: _ClaudeRun) -> None:
        assert run.process.stdout is not None
        try:
            while raw := await run.process.stdout.readline():
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as error:
                    await self._terminal(
                        run,
                        AgentRunPhase.FAILED,
                        error=f"malformed Claude stream-json event: {error}",
                    )
                    return
                await self._translate(run, message)
                if run.phase.terminal:
                    return
            return_code = await run.process.wait()
            if run.phase is AgentRunPhase.CANCELLING:
                return
            if not run.phase.terminal:
                stderr = await self._stderr(run)
                await self._terminal(
                    run,
                    AgentRunPhase.FAILED,
                    error=f"Claude process exited with code {return_code}: {stderr}".rstrip(),
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not run.phase.terminal and run.phase is not AgentRunPhase.CANCELLING:
                await self._terminal(
                    run,
                    AgentRunPhase.FAILED,
                    error=f"{type(error).__name__}: {error}",
                )

    async def _translate(self, run: _ClaudeRun, message: Mapping[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "stream_event":
            event = message.get("event")
            if isinstance(event, Mapping):
                delta = event.get("delta")
                if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
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
            return
        if message_type != "result":
            return
        usage = message.get("usage")
        if isinstance(usage, Mapping):
            await self._append(
                run,
                AgentUsageUpdated(
                    worker_id=run.handle.worker_id,
                    event_id=str(uuid.uuid4()),
                    sequence=len(run.events) + 1,
                    occurred_at=utc_now(),
                    locator=run.handle.locator,
                    input_tokens=_nonnegative_int(usage.get("input_tokens")),
                    cached_input_tokens=_nonnegative_int(
                        usage.get("cache_read_input_tokens")
                    ),
                    output_tokens=_nonnegative_int(usage.get("output_tokens")),
                    cost_usd=_optional_float(message.get("total_cost_usd")),
                ),
            )
        is_error = bool(message.get("is_error")) or message.get("subtype") != "success"
        if is_error:
            await self._terminal(
                run,
                AgentRunPhase.FAILED,
                error=str(message.get("result") or "Claude run failed"),
            )
        else:
            await self._terminal(
                run,
                AgentRunPhase.SUCCEEDED,
                result=str(message.get("result") or ""),
            )

    async def _terminal(
        self,
        run: _ClaudeRun,
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

    async def _append(self, run: _ClaudeRun, event: AgentEvent) -> None:
        async with run.condition:
            run.events.append(event)
            run.condition.notify_all()

    async def _stderr(self, run: _ClaudeRun) -> str:
        if run.process.stderr is None:
            return ""
        return (await run.process.stderr.read()).decode(errors="replace").strip()

    def _require(self, handle: AgentRunHandle) -> _ClaudeRun:
        run = self._runs.get(handle.worker_id)
        if run is None or run.handle != handle:
            raise KeyError(f"unknown Claude handle for {handle.worker_id!r}")
        return run


def _nonnegative_int(value: object) -> int:
    return max(0, value) if isinstance(value, int) else 0


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
