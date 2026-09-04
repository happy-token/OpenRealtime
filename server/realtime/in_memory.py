"""Deterministic reference adapter used by the Realtime contract suite."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

from server.conversation_journal import ConversationItem, StructuredContent, TextContent
from server.core.interaction_context import InteractionContext
from server.realtime.errors import ContextVisibilityError
from server.realtime.protocol.commands import (
    AppendSpeechText,
    CancelResponse,
    CancelSpeech,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    ProjectCommittedItem,
    RealtimeCommand,
    ReportPlaybackProgress,
    RequestResponse,
    StartSpeech,
)
from server.realtime.protocol.events import (
    ItemDeliveryCompleted,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemProjected,
    RealtimeEvent,
    ResponseCancelled,
    ResponseRequested,
    SpeechCancelled,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
)
from server.realtime.scope import conversation_scope
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryStore,
    SpeechLifecycle,
)

_CLOSED = object()


class InMemoryRealtimeConversation:
    def __init__(
        self,
        *,
        context: InteractionContext,
        event_queue_size: int = 64,
        speech_deliveries: SpeechDeliveryStore | None = None,
    ) -> None:
        if event_queue_size < 1:
            raise ValueError("event_queue_size must be positive")
        self._context = context
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue(
            maxsize=event_queue_size
        )
        self._sequence = 0
        self._closed = False
        self._commands_by_idempotency_key: dict[str, RealtimeCommand] = {}
        self._active_response_ids: set[str] = set()
        self._last_projected_thread_sequence = 0
        self._projected_thread_sequence_by_item_id: dict[str, int] = {}
        self._projected_items_by_id: dict[str, ConversationItem] = {}
        self._speech_lifecycle = SpeechLifecycle(
            speech_deliveries or InMemorySpeechDeliveryStore()
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("realtime conversation is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        previous = self._commands_by_idempotency_key.get(command.idempotency_key)
        if previous is not None:
            if previous != command:
                raise ValueError("idempotency key was reused with different command content")
            return
        if isinstance(command, StartSpeech):
            await self._emit(
                await self._speech_lifecycle.start(
                    command,
                    sequence=self._next_sequence,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, AppendSpeechText):
            await self._emit(
                await self._speech_lifecycle.append(
                    command,
                    sequence=self._next_sequence,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CommitSpeech):
            await self._emit(
                await self._speech_lifecycle.commit(
                    command,
                    sequence=self._next_sequence,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ReportPlaybackProgress):
            await self._emit(
                await self._speech_lifecycle.report(
                    command,
                    sequence=self._next_sequence,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CancelSpeech):
            await self._emit(
                await self._speech_lifecycle.cancel(
                    command,
                    sequence=self._next_sequence,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ProjectCommittedItem):
            await self._emit(
                ItemProjected(
                    event_id=str(uuid.uuid4()),
                    context=command.context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    item_id=command.item.item_id,
                    thread_sequence=command.item.sequence,
                    thread_version=command.item.thread_version,
                )
            )
            self._last_projected_thread_sequence = max(
                self._last_projected_thread_sequence,
                command.item.sequence,
            )
            self._projected_thread_sequence_by_item_id[command.item.item_id] = command.item.sequence
            self._projected_items_by_id[command.item.item_id] = command.item
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, DeliverItem):
            thread_sequence = self._projected_thread_sequence_by_item_id.get(command.item_id)
            if thread_sequence is None:
                raise ContextVisibilityError(f"item {command.item_id!r} has not been projected")
            await self._emit(
                ItemDeliveryQueued(
                    event_id=str(uuid.uuid4()),
                    context=command.context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    delivery_id=command.delivery_id,
                    item_id=command.item_id,
                    minimum_thread_sequence=thread_sequence,
                    mode=command.mode,
                    timing=command.timing,
                    priority=command.priority,
                )
            )
            await self._emit(
                ItemDeliveryStarted(
                    event_id=str(uuid.uuid4()),
                    context=command.context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    delivery_id=command.delivery_id,
                    item_id=command.item_id,
                    minimum_thread_sequence=thread_sequence,
                    mode=command.mode,
                )
            )
            if command.mode is DeliveryMode.MODEL_RESPONSE:
                response_id = f"delivery:{command.delivery_id}"
                await self.send(
                    RequestResponse(
                        command_id=f"response:{command.command_id}",
                        idempotency_key=f"response:{command.idempotency_key}",
                        context=command.context,
                        response_id=response_id,
                        minimum_thread_sequence=thread_sequence,
                        output_item_id=command.output_item_id,
                    )
                )
            elif command.mode is DeliveryMode.SPEECH:
                await self._deliver_item_as_speech(command)
                await self._complete_delivery(command)
            else:
                await self._complete_delivery(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, RequestResponse):
            if command.minimum_thread_sequence > self._last_projected_thread_sequence:
                raise ContextVisibilityError(
                    "response requires thread sequence "
                    f"{command.minimum_thread_sequence}, but engine has projected through "
                    f"{self._last_projected_thread_sequence}"
                )
            await self._emit(
                ResponseRequested(
                    event_id=str(uuid.uuid4()),
                    context=replace(command.context, response_id=command.response_id),
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    response_id=command.response_id,
                    minimum_thread_sequence=command.minimum_thread_sequence,
                )
            )
            self._active_response_ids.add(command.response_id)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CancelResponse):
            if command.response_id not in self._active_response_ids:
                raise ValueError("response identity is not active")
            self._active_response_ids.remove(command.response_id)
            await self._emit(
                ResponseCancelled(
                    event_id=str(uuid.uuid4()),
                    context=replace(command.context, response_id=command.response_id),
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    response_id=command.response_id,
                    response_sequence=1,
                    reason=command.reason,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        raise TypeError(f"unsupported realtime command: {type(command).__name__}")

    async def _deliver_item_as_speech(self, command: DeliverItem) -> None:
        item = self._projected_items_by_id[command.item_id]
        text = _spoken_text(item)
        speech_id = f"delivery:{command.delivery_id}"
        await self.send(
            StartSpeech(
                command_id=f"speech-start:{command.command_id}",
                idempotency_key=f"speech-start:{command.idempotency_key}",
                context=command.context,
                speech_id=speech_id,
                source_item_id=command.item_id,
            )
        )
        await self.send(
            AppendSpeechText(
                command_id=f"speech-text:{command.command_id}",
                idempotency_key=f"speech-text:{command.idempotency_key}",
                context=command.context,
                speech_id=speech_id,
                text_sequence=1,
                delta=text,
            )
        )
        await self.send(
            CommitSpeech(
                command_id=f"speech-commit:{command.command_id}",
                idempotency_key=f"speech-commit:{command.idempotency_key}",
                context=command.context,
                speech_id=speech_id,
            )
        )
        await self.send(
            ReportPlaybackProgress(
                command_id=f"speech-progress:{command.command_id}",
                idempotency_key=f"speech-progress:{command.idempotency_key}",
                context=command.context,
                speech_id=speech_id,
                delivered_text_end=len(text),
                played_audio_end_us=0,
                completed=True,
            )
        )

    async def _complete_delivery(self, command: DeliverItem) -> None:
        await self._emit(
            ItemDeliveryCompleted(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                mode=command.mode,
            )
        )

    async def _emit(self, event: RealtimeEvent) -> None:
        await self._events.put(event)

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            assert isinstance(
                event,
                (
                    ItemProjected,
                    ItemDeliveryCompleted,
                    ItemDeliveryQueued,
                    ItemDeliveryStarted,
                    ResponseRequested,
                    ResponseCancelled,
                    SpeechStarted,
                    SpeechTextAccepted,
                    SpeechTextCommitted,
                    SpeechCancelled,
                    SpeechPlaybackProgress,
                ),
            )
            yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._speech_lifecycle.close()
        self._active_response_ids.clear()
        await self._events.put(_CLOSED)


def _spoken_text(item: ConversationItem) -> str:
    if item.spoken is not None:
        return item.spoken.text
    text_parts = [part.text for part in item.content if isinstance(part, TextContent)]
    if text_parts:
        return "\n".join(text_parts)
    for part in item.content:
        if not isinstance(part, StructuredContent):
            continue
        value = part.value
        for key in ("spoken_text", "result", "message", "error"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    raise ValueError(f"projected item {item.item_id!r} has no deterministic spoken text")
