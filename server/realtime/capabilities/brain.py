"""Typed streaming Brain capability and adapter for the existing Brain seam."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Protocol, cast

from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.observability.telemetry import telemetry_generation_scope
from server.realtime.capabilities.brain_streaming import (
    BrainDelegationCall,
    BrainToolCall,
    StreamingTextBrain,
)
from server.realtime.capabilities.tool_results import (
    ToolResultChannel,
    ToolResultFeedback,
)
from server.tools.canonical import LatencyClass

_CLOSED = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestBrainResponse:
    response_id: str
    turn: TurnContent
    context: InteractionContext | None = None

    def __post_init__(self) -> None:
        if not self.response_id:
            raise ValueError("Brain response identity must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelBrainResponse:
    response_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.response_id or not self.reason:
            raise ValueError("Brain cancellation identity and reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitBrainToolResult:
    response_id: str
    call_id: str
    success: bool
    model_output: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.call_id or not self.model_output:
            raise ValueError("Brain tool result identity and output must be non-empty")
        if self.success and self.error_code is not None:
            raise ValueError("successful Brain tool result cannot carry an error code")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainResponseStarted:
    context: InteractionContext
    response_id: str
    response_sequence: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainTextDelta:
    context: InteractionContext
    response_id: str
    response_sequence: int
    delta: str

    def __post_init__(self) -> None:
        if not self.delta or self.response_sequence < 1:
            raise ValueError("Brain text delta must be non-empty and ordered")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainToolRequested:
    context: InteractionContext
    response_id: str
    response_sequence: int
    call_id: str
    tool_name: str
    tool_version: str
    arguments: dict[str, object]
    latency: LatencyClass

    def __post_init__(self) -> None:
        if not all((self.response_id, self.call_id, self.tool_name, self.tool_version)):
            raise ValueError("Brain tool request identity must be non-empty")
        if self.response_sequence < 1:
            raise ValueError("Brain tool request sequence must be positive")
        if self.context.call_id != self.call_id:
            raise ValueError("Brain tool request context must carry the same call_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainDelegationRequested:
    context: InteractionContext
    response_id: str
    response_sequence: int
    delegation_request_id: str
    instruction: str
    agent_name: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.delegation_request_id or not self.instruction:
            raise ValueError("Brain delegation request identity must be non-empty")
        if self.response_sequence < 1:
            raise ValueError("Brain delegation request sequence must be positive")
        if self.context.worker_id is not None:
            raise ValueError("Brain delegation request cannot claim a worker_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainResponseCompleted:
    context: InteractionContext
    response_id: str
    response_sequence: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainResponseFailed:
    context: InteractionContext
    response_id: str
    response_sequence: int
    error: str

    def __post_init__(self) -> None:
        if not self.error:
            raise ValueError("Brain failure must carry an error")


BrainCommand = RequestBrainResponse | CancelBrainResponse | SubmitBrainToolResult
BrainEvent = (
    BrainResponseStarted
    | BrainTextDelta
    | BrainToolRequested
    | BrainDelegationRequested
    | BrainResponseCompleted
    | BrainResponseFailed
)


class BrainCapabilitySession(Protocol):
    async def send(self, command: BrainCommand) -> None: ...

    def events(self) -> AsyncIterator[BrainEvent]: ...

    async def close(self) -> None: ...


class BrainCapabilityProvider(Protocol):
    async def open(self, *, context: InteractionContext) -> BrainCapabilitySession: ...


class LegacyBrainCapabilityAdapter:
    def __init__(self, brain: StreamingTextBrain) -> None:
        self._brain = brain

    async def open(self, *, context: InteractionContext) -> LegacyBrainCapabilitySession:
        return LegacyBrainCapabilitySession(context=context, brain=self._brain)


class LegacyBrainCapabilitySession:
    def __init__(self, *, context: InteractionContext, brain: StreamingTextBrain) -> None:
        self._context = context
        self._brain = brain
        self._events: asyncio.Queue[BrainEvent | object] = asyncio.Queue(maxsize=64)
        self._responses: dict[str, asyncio.Task[None]] = {}
        self._tool_results: dict[str, ToolResultChannel] = {}
        self._closed = False

    async def send(self, command: BrainCommand) -> None:
        if self._closed:
            raise RuntimeError("Brain capability session is closed")
        if isinstance(command, CancelBrainResponse):
            task = self._responses.get(command.response_id)
            if task is None:
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return
        if isinstance(command, SubmitBrainToolResult):
            channel = self._tool_results.get(command.response_id)
            if channel is None:
                raise ValueError("Brain response is not waiting for tool results")
            await channel.submit(
                ToolResultFeedback(
                    response_id=command.response_id,
                    call_id=command.call_id,
                    success=command.success,
                    model_output=command.model_output,
                    error_code=command.error_code,
                )
            )
            return
        response_context = command.context or self._context
        if command.turn.generation != response_context.generation:
            raise ValueError("Brain turn and capability generation must match")
        if command.response_id in self._responses:
            raise ValueError("Brain response identity is already active")
        self._responses[command.response_id] = asyncio.create_task(
            self._run(command, response_context=response_context),
            name=f"brain-capability-{command.response_id}",
        )

    async def _run(
        self,
        command: RequestBrainResponse,
        *,
        response_context: InteractionContext,
    ) -> None:
        response_context = replace(response_context, response_id=command.response_id)
        with telemetry_generation_scope(response_context.generation):
            await self._run_correlated(command, response_context=response_context)

    async def _run_correlated(
        self,
        command: RequestBrainResponse,
        *,
        response_context: InteractionContext,
    ) -> None:
        sequence = 1
        tool_results = ToolResultChannel(command.response_id)
        self._tool_results[command.response_id] = tool_results
        await self._events.put(
            BrainResponseStarted(
                context=response_context,
                response_id=command.response_id,
                response_sequence=sequence,
            )
        )
        try:
            stream_with_tools = getattr(self._brain, "stream_with_tools", None)
            stream = (
                stream_with_tools(command.turn, tool_results=tool_results)
                if stream_with_tools is not None
                else self._brain.stream(command.turn)
            )
            async for output in stream:
                if not output:
                    continue
                sequence += 1
                if isinstance(output, str):
                    await self._events.put(
                        BrainTextDelta(
                            context=response_context,
                            response_id=command.response_id,
                            response_sequence=sequence,
                            delta=output,
                        )
                    )
                elif isinstance(output, BrainToolCall):
                    await self._events.put(
                        BrainToolRequested(
                            context=replace(response_context, call_id=output.call_id),
                            response_id=command.response_id,
                            response_sequence=sequence,
                            call_id=output.call_id,
                            tool_name=output.tool_name,
                            tool_version=output.tool_version,
                            arguments=output.arguments,
                            latency=output.latency,
                        )
                    )
                elif isinstance(output, BrainDelegationCall):
                    await self._events.put(
                        BrainDelegationRequested(
                            context=response_context,
                            response_id=command.response_id,
                            response_sequence=sequence,
                            delegation_request_id=output.delegation_request_id,
                            instruction=output.instruction,
                            agent_name=output.agent_name,
                        )
                    )
                else:
                    raise TypeError(
                        f"unsupported Brain stream event: {type(output).__name__}"
                    )
            sequence += 1
            await self._events.put(
                BrainResponseCompleted(
                    context=response_context,
                    response_id=command.response_id,
                    response_sequence=sequence,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures become typed events
            error_message = str(error).strip() or type(error).__name__
            await self._events.put(
                BrainResponseFailed(
                    context=response_context,
                    response_id=command.response_id,
                    response_sequence=sequence + 1,
                    error=error_message,
                )
            )
        finally:
            await tool_results.close()
            self._tool_results.pop(command.response_id, None)
            self._responses.pop(command.response_id, None)

    async def events(self) -> AsyncIterator[BrainEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(BrainEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = tuple(self._responses.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._events.put(_CLOSED)
