"""Typed streaming Brain capability and adapter for the existing Brain seam."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Protocol, cast

from server.core.async_stream import OwnedStreamCleanupError
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
    request_token: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id:
            raise ValueError("Brain response identity must be non-empty")
        _validate_request_token(self.request_token)


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelBrainResponse:
    response_id: str
    reason: str
    request_token: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.reason:
            raise ValueError("Brain cancellation identity and reason must be non-empty")
        _validate_request_token(self.request_token)


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitBrainToolResult:
    response_id: str
    call_id: str
    success: bool
    model_output: str
    error_code: str | None = None
    request_token: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.call_id or not self.model_output:
            raise ValueError("Brain tool result identity and output must be non-empty")
        if self.success and self.error_code is not None:
            raise ValueError("successful Brain tool result cannot carry an error code")
        _validate_request_token(self.request_token)


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainResponseStarted:
    context: InteractionContext
    response_id: str
    response_sequence: int = 1
    request_token: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainTextDelta:
    context: InteractionContext
    response_id: str
    response_sequence: int
    delta: str
    request_token: str | None = None

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
    request_token: str | None = None

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
    request_token: str | None = None

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
    request_token: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BrainResponseFailed:
    context: InteractionContext
    response_id: str
    response_sequence: int
    error: str
    request_token: str | None = None

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


def _validate_request_token(token: str | None) -> None:
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ValueError("Brain request token must be non-empty when provided")


@dataclass(slots=True)
class _BrainRequestOwner:
    request_token: str | None
    tool_results: ToolResultChannel
    task: asyncio.Task[None] | None = None
    run_entered: bool = False
    cleanup_confirmed: bool = False
    cleanup_error: Exception | None = None


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
        self._requests: dict[str, _BrainRequestOwner] = {}
        self._closed = False
        self._close_error: str | None = None
        self._close_task: asyncio.Task[None] | None = None

    async def send(self, command: BrainCommand) -> None:
        if self._closed:
            raise RuntimeError("Brain capability session is closed")
        if isinstance(command, CancelBrainResponse):
            owner = self._requests.get(command.response_id)
            if owner is None or owner.request_token != command.request_token:
                return
            task = owner.task
            assert task is not None
            if not task.cancelling():
                task.cancel()
            results = await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            for result in results:
                if isinstance(result, Exception) and owner.cleanup_error is None:
                    owner.cleanup_error = result
            if not owner.run_entered:
                await owner.tool_results.close()
                owner.cleanup_confirmed = True
            if not owner.cleanup_confirmed:
                detail = f": {owner.cleanup_error}" if owner.cleanup_error is not None else ""
                raise RuntimeError(f"Brain request cleanup was not confirmed{detail}") from owner.cleanup_error
            return
        if isinstance(command, SubmitBrainToolResult):
            owner = self._requests.get(command.response_id)
            if owner is None:
                raise ValueError("Brain response is not waiting for tool results")
            if owner.request_token != command.request_token:
                raise ValueError("Brain tool result belongs to a different request attempt")
            await owner.tool_results.submit(
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
        if command.response_id in self._requests:
            raise ValueError("Brain response identity is already active")
        owner = _BrainRequestOwner(command.request_token, ToolResultChannel(command.response_id))
        self._requests[command.response_id] = owner
        owner.task = asyncio.create_task(
            self._run(command, response_context=response_context, owner=owner),
            name=f"brain-capability-{command.response_id}",
        )
        def finished(task: asyncio.Task[None]) -> None:
            if not task.cancelled():
                error = task.exception()
                if isinstance(error, Exception) and not owner.cleanup_confirmed:
                    owner.cleanup_error = error
            self._release_request(command.response_id, owner)

        owner.task.add_done_callback(finished)

    def _release_request(self, response_id: str, owner: _BrainRequestOwner) -> None:
        # Also runs when cancellation happens before the coroutine's first step.
        if (owner.cleanup_confirmed or not owner.run_entered) and self._requests.get(response_id) is owner:
            self._requests.pop(response_id)

    async def _run(
        self,
        command: RequestBrainResponse,
        *,
        response_context: InteractionContext,
        owner: _BrainRequestOwner,
    ) -> None:
        owner.run_entered = True
        response_context = replace(response_context, response_id=command.response_id)
        with telemetry_generation_scope(response_context.generation):
            await self._run_correlated(command, response_context=response_context, owner=owner)

    async def _run_correlated(
        self,
        command: RequestBrainResponse,
        *,
        response_context: InteractionContext,
        owner: _BrainRequestOwner,
    ) -> None:
        sequence = 1
        tool_results = owner.tool_results
        iterator: AsyncIterator[object] | None = None
        try:
            await self._events.put(
                BrainResponseStarted(context=response_context, response_id=command.response_id,
                    response_sequence=sequence, request_token=command.request_token)
            )
            stream_with_tools = getattr(self._brain, "stream_with_tools", None)
            stream = (
                stream_with_tools(command.turn, tool_results=tool_results)
                if stream_with_tools is not None
                else self._brain.stream(command.turn)
            )
            iterator = stream.__aiter__()
            async for output in iterator:
                if self._closed or self._requests.get(command.response_id) is not owner:
                    return
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
                            request_token=command.request_token,
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
                            request_token=command.request_token,
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
                            request_token=command.request_token,
                        )
                    )
                else:
                    raise TypeError(
                        f"unsupported Brain stream event: {type(output).__name__}"
                    )
            sequence += 1
            # Exhausting a custom iterator does not necessarily close its SDK
            # stream. Finish that ownership before publishing completion.
            close_stream = getattr(iterator, "aclose", None)
            if close_stream is not None:
                await close_stream()
            iterator = None
            if self._closed:
                return
            await self._events.put(
                BrainResponseCompleted(
                    context=response_context,
                    response_id=command.response_id,
                    response_sequence=sequence,
                    request_token=command.request_token,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            current = asyncio.current_task()
            if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                owner.cleanup_error = error
                if current is not None and current.cancelling():
                    raise
            if self._closed:
                return
            error_message = str(error).strip() or type(error).__name__
            await self._events.put(
                BrainResponseFailed(
                    context=response_context,
                    response_id=command.response_id,
                    response_sequence=sequence + 1,
                    error=error_message,
                    request_token=command.request_token,
                )
            )
        finally:
            try:
                if iterator is not None:
                    close_stream = getattr(iterator, "aclose", None)
                    if close_stream is not None:
                        await close_stream()
                await tool_results.close()
                owner.cleanup_confirmed = owner.cleanup_error is None
            except Exception as error:
                owner.cleanup_error = error
                raise
            finally:
                self._release_request(command.response_id, owner)

    async def events(self) -> AsyncIterator[BrainEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(BrainEvent, event)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owners(), name="brain-capability-close")
            self._close_task.add_done_callback(self._observe_close)
        # A cancelled waiter is not a resource close acknowledgement. All
        # concurrent/repeated callers join the original owned cleanup task.
        await asyncio.shield(self._close_task)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _close_owners(self) -> None:
        owners = tuple(self._requests.values())
        tasks = tuple(owner.task for owner in owners if owner.task is not None)
        while not self._events.empty():
            self._events.get_nowait()
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
        for owner in owners:
            if not owner.run_entered:
                await owner.tool_results.close()
                owner.cleanup_confirmed = True
            if not owner.cleanup_confirmed:
                detail = f": {owner.cleanup_error}" if owner.cleanup_error is not None else ""
                self._close_error = f"Brain capability close did not confirm provider cleanup{detail}"
                raise RuntimeError(self._close_error) from owner.cleanup_error
        self._requests.clear()
        # No consumer remains after a protocol fault; a full output queue must
        # not prevent cancelling this delegate and releasing its request owners.
        while not self._events.empty():
            self._events.get_nowait()
        self._events.put_nowait(_CLOSED)
