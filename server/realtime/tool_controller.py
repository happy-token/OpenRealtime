"""Application control plane for Realtime tool requests and result injection."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    StructuredContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.observability.telemetry import telemetry_generation_scope
from server.realtime.protocol import (
    AppendItem,
    ConfirmationRequested,
    ProjectCommittedItem,
    RealtimeCapabilityFailed,
    RealtimeCommand,
    RealtimeConversation,
    RealtimeEvent,
    RecordOutputStop,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ToolRequested,
)
from server.realtime.protocol.engine import (
    is_output_context_current,
    is_output_deliverable,
    is_sentence_permit_current,
)
from server.realtime.scope import conversation_scope
from server.tools.control import (
    CommittedToolItemsProvider,
    CommittedToolResultProvider,
    ToolCancellation,
    ToolControlCancelled,
    ToolControlHandler,
    ToolControlResult,
)
from server.tools.policy_gateway import ConfirmationChannel, ToolRequest

_CLOSED = object()


class RealtimeToolController:
    """Execute control requests without blocking the Realtime event stream."""

    def __init__(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
        committed_projection: RealtimeConversation | None = None,
        tool_control_handler_factory: Callable[[], ToolControlHandler],
    ) -> None:
        self._context = context
        self._conversation = conversation
        self._committed_projection = committed_projection or conversation
        self._tool_control_handler_factory = tool_control_handler_factory
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue()
        self._cancellations_by_response_id: dict[str, ToolCancellation] = {}
        self._handlers_by_response_id: dict[str, ToolControlHandler] = {}
        self._tasks_by_call_id: dict[str, asyncio.Task[None]] = {}
        self._seen_call_ids: set[str] = set()
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._pump_task = asyncio.create_task(
            self._pump_events(),
            name=f"realtime-tools-{context.voice_session_id}",
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("realtime tool controller is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        if isinstance(command, RecordOutputStop):
            # Saving a fenced fact does not mutate tool or actor control state.
            await self._conversation.send(command)
            return
        async with self._send_lock:
            await self._conversation.send(command)

    async def _pump_events(self) -> None:
        try:
            async for event in self._conversation.events():
                if not self.output_delivery_allowed(event):
                    continue
                if isinstance(event, ToolRequested):
                    self._start_tool(event)
                elif isinstance(
                    event,
                    (ResponseCompleted, ResponseCancelled, ResponseFailed),
                ):
                    cancellation = self._cancellations_by_response_id.pop(
                        event.response_id,
                        None,
                    )
                    self._handlers_by_response_id.pop(event.response_id, None)
                    if cancellation is not None and not isinstance(
                        event,
                        ResponseCompleted,
                    ):
                        cancellation.cancel(
                            event.reason
                            if isinstance(event, ResponseCancelled)
                            else "response_failed"
                        )
                await self._events.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - decorator failure is public
            await self._events.put(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=self._context,
                    conversation_sequence=1,
                    occurred_at=datetime.now(UTC),
                    capability="realtime_tool_controller",
                    error=f"{type(error).__name__}: {error}",
                )
            )
        finally:
            await self._events.put(_CLOSED)

    def _start_tool(self, event: ToolRequested) -> None:
        if event.call_id in self._seen_call_ids:
            return
        self._seen_call_ids.add(event.call_id)
        cancellation = self._cancellations_by_response_id.setdefault(
            event.response_id,
            ToolCancellation(),
        )
        handler = self._handlers_by_response_id.get(event.response_id)
        if handler is None:
            handler = self._tool_control_handler_factory()
            self._handlers_by_response_id[event.response_id] = handler
        task = asyncio.create_task(
            self._run_tool(event, cancellation=cancellation, handler=handler),
            name=f"realtime-tool-{event.call_id}",
        )
        self._tasks_by_call_id[event.call_id] = task

    async def _run_tool(
        self,
        event: ToolRequested,
        *,
        cancellation: ToolCancellation,
        handler: ToolControlHandler,
    ) -> None:
        with telemetry_generation_scope(event.context.generation):
            await self._run_tool_correlated(
                event,
                cancellation=cancellation,
                handler=handler,
            )

    async def _run_tool_correlated(
        self,
        event: ToolRequested,
        *,
        cancellation: ToolCancellation,
        handler: ToolControlHandler,
    ) -> None:
        request = ToolRequest(
            context=event.context,
            call_id=event.call_id,
            tool_name=event.tool_name,
            tool_version=event.tool_version,
            arguments=dict(event.arguments),
            origin=event.origin,
        )
        try:
            if not self.output_delivery_allowed(event):
                return
            try:
                feedback = await handler.handle(
                    request,
                    cancellation,
                )
            except ToolControlCancelled:
                return
            except Exception:  # noqa: BLE001 - safe model-facing failure
                feedback = ToolControlResult(
                    call_id=event.call_id,
                    success=False,
                    model_output="工具执行失败，请稍后重试。",
                    error_code="execution_failed",
                )
            if cancellation.is_cancelled or self._closed:
                return
            async with self._send_lock:
                if isinstance(handler, CommittedToolItemsProvider):
                    items = handler.committed_tool_items(event.call_id)
                elif isinstance(handler, CommittedToolResultProvider):
                    result = handler.committed_tool_result(event.call_id)
                    items = (result,) if result is not None else ()
                else:
                    items = ()
                for item in items:
                    await self._committed_projection.send(
                        ProjectCommittedItem(
                            command_id=(
                                f"project-tool-item:{event.call_id}:{item.sequence}"
                            ),
                            idempotency_key=f"project:{item.item_id}:{item.sequence}",
                            context=event.context,
                            item=item,
                        )
                    )
                    if item.kind is ConversationItemKind.CONFIRMATION_REQUESTED:
                        await self._events.put(_confirmation_event(event, item))
                if not any(
                    item.kind is ConversationItemKind.TOOL_RESULT for item in items
                ):
                    await self._conversation.send(_tool_result_command(event, feedback))
        except Exception as error:  # noqa: BLE001 - projection failure is public
            await self._events.put(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=event.context,
                    conversation_sequence=event.conversation_sequence + 1,
                    occurred_at=datetime.now(UTC),
                    capability="realtime_tool_result_projection",
                    error=f"{type(error).__name__}: {error}",
                )
            )
        finally:
            self._tasks_by_call_id.pop(event.call_id, None)

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._iterate_events()

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit) -> bool:
        return not self._closed and is_sentence_permit_current(self._conversation, permit)

    def output_context_current(self, event: RealtimeEvent) -> bool:
        return not self._closed and is_output_context_current(self._conversation, event)

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return is_output_deliverable(self._conversation, event)

    async def _iterate_events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            typed_event = cast(RealtimeEvent, event)
            if self.output_delivery_allowed(typed_event):
                yield typed_event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._handlers_by_response_id.clear()
        for cancellation in self._cancellations_by_response_id.values():
            cancellation.cancel("conversation_closed")
        tasks = tuple(self._tasks_by_call_id.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._conversation.close()
        await self._pump_task


def _tool_result_command(
    event: ToolRequested,
    feedback: ToolControlResult,
) -> AppendItem:
    item_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"urn:voiceagent:tool-result:{event.context.thread_id}:{event.call_id}",
        )
    )
    metadata: dict[str, object] = {
        "call_id": event.call_id,
        "success": feedback.success,
        "tool_name": event.tool_name,
        "tool_version": event.tool_version,
    }
    if feedback.error_code is not None:
        metadata["error_code"] = feedback.error_code
    return AppendItem(
        command_id=f"append-tool-result:{event.call_id}",
        idempotency_key=f"append-tool-result:{event.call_id}",
        context=event.context,
        draft=ConversationItemDraft(
            item_id=item_id,
            context=event.context,
            kind=ConversationItemKind.TOOL_RESULT,
            status=(
                ConversationItemStatus.COMPLETED
                if feedback.success
                else ConversationItemStatus.FAILED
            ),
            producer="realtime-tool-controller",
            content=(TextContent(feedback.model_output),),
            visibility=frozenset(
                {
                    ConversationVisibility.MODEL,
                    ConversationVisibility.INTERNAL,
                }
            ),
            provider_metadata=metadata,
            occurred_at=datetime.now(UTC),
        ),
    )


def _confirmation_event(event: ToolRequested, item) -> ConfirmationRequested:
    structured = next(
        (part.value for part in item.content if isinstance(part, StructuredContent)),
        None,
    )
    if structured is None:
        raise ValueError("confirmation item requires structured content")
    confirmation_id = structured.get("confirmation_id")
    action_digest = structured.get("action_digest")
    summary = structured.get("action_summary")
    required_channel = structured.get("required_channel")
    expires_at = structured.get("expires_at")
    if not all(
        isinstance(value, str)
        for value in (
            confirmation_id,
            action_digest,
            summary,
            required_channel,
            expires_at,
        )
    ):
        raise TypeError("confirmation item authority fields are invalid")
    return ConfirmationRequested(
        event_id=str(uuid.uuid4()),
        context=replace(event.context, confirmation_id=confirmation_id),
        conversation_sequence=event.conversation_sequence + 1,
        occurred_at=item.occurred_at,
        response_id=event.response_id,
        response_sequence=event.response_sequence + 1,
        confirmation_id=confirmation_id,
        action_digest=action_digest,
        summary=summary,
        required_channel=ConfirmationChannel(required_channel),
        expires_at=datetime.fromisoformat(expires_at),
    )
