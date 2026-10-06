"""Journal-backed orchestration for automatic realtime turns.

The realtime engine owns media and provider state.  This controller owns the
small amount of product policy needed to turn a completed user transcript into
a durable Conversation Item, request a response only after projection, and
settle the assistant's semantic/display/spoken representations.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    DisplayContent,
    JournalScope,
    SpokenContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.observability import RealtimeObserver
from server.realtime.protocol.commands import (
    AppendItem,
    DeliverItem,
    DeliveryMode,
    RealtimeCommand,
    RequestResponse,
    SpeechContextPolicy,
)
from server.realtime.protocol.engine import RealtimeConversation, is_output_deliverable
from server.realtime.protocol.events import (
    DisplayContentDelta,
    InputTranscriptCompleted,
    ItemDeliveryStarted,
    ItemProjected,
    RealtimeEvent,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechCancelled,
    SpeechStarted,
    SpeechTextCommitted,
    SpokenContentDelta,
)
from server.realtime.scope import conversation_scope


@dataclass(slots=True)
class _ResponseDraft:
    context: InteractionContext
    parent_item_id: str | None
    display_parts: list[str] = field(default_factory=list)
    spoken_parts: list[str] = field(default_factory=list)
    revision_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _SpeechDraft:
    source_item_id: str | None
    context_policy: SpeechContextPolicy


@dataclass(frozen=True, slots=True)
class _PumpStopped:
    error: Exception | None = None


class RealtimeTurnController:
    """Compose automatic turn policy around any realtime conversation.

    The wrapped conversation is expected to provide Journal-first ``AppendItem``
    handling.  The controller deliberately depends only on the public realtime
    protocol, keeping engine/provider implementations replaceable.
    """

    def __init__(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
        observer: RealtimeObserver | None = None,
    ) -> None:
        self._context = context
        self._conversation = conversation
        self._observer = observer
        self._events: asyncio.Queue[RealtimeEvent | _PumpStopped] = asyncio.Queue()
        self._pending_user_items: dict[str, InputTranscriptCompleted] = {}
        self._response_drafts: dict[str, _ResponseDraft] = {}
        self._response_parents: dict[str, str] = {}
        self._response_output_item_ids: dict[str, str] = {}
        self._direct_delivery_responses: set[str] = set()
        self._speech_drafts: dict[str, _SpeechDraft] = {}
        self._closed = False
        self._pump_task = asyncio.create_task(
            self._pump_events(), name="realtime-turn-controller"
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("realtime turn controller is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        if isinstance(command, RequestResponse):
            output_item_id = command.output_item_id or self._stable_id(
                command.context,
                f"assistant-output:{command.response_id}",
            )
            self._response_output_item_ids[command.response_id] = output_item_id
            command = replace(command, output_item_id=output_item_id)
        elif isinstance(command, DeliverItem) and command.mode is DeliveryMode.MODEL_RESPONSE:
            response_id = f"delivery:{command.delivery_id}"
            output_item_id = command.output_item_id or self._stable_id(
                command.context,
                f"assistant-output:{response_id}",
            )
            self._response_output_item_ids[response_id] = output_item_id
            command = replace(command, output_item_id=output_item_id)
        await self._conversation.send(command)

    async def _pump_events(self) -> None:
        try:
            async for event in self._conversation.events():
                await self._handle_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - surface provider failures to consumers
            await self._events.put(_PumpStopped(error))
        else:
            await self._events.put(_PumpStopped())

    async def _handle_event(self, event: RealtimeEvent) -> None:
        if isinstance(event, InputTranscriptCompleted):
            await self._commit_user_transcript(event)
        elif isinstance(event, ItemProjected):
            await self._request_response_for_projected_user(event)
        elif isinstance(event, ItemDeliveryStarted):
            if event.mode is not DeliveryMode.MODEL_RESPONSE:
                self._direct_delivery_responses.add(f"delivery:{event.delivery_id}")
        elif isinstance(event, SpeechStarted):
            self._speech_drafts[event.speech_id] = _SpeechDraft(
                source_item_id=event.source_item_id,
                context_policy=event.context_policy,
            )
        elif isinstance(event, SpeechTextCommitted):
            await self._settle_external_speech(
                speech_id=event.speech_id,
                text=event.spoken_text,
                context=event.context,
                occurred_at=event.occurred_at,
                status=ConversationItemStatus.COMPLETED,
            )
        elif isinstance(event, SpeechCancelled):
            await self._settle_external_speech(
                speech_id=event.speech_id,
                text=event.accepted_text,
                context=event.context,
                occurred_at=event.occurred_at,
                status=ConversationItemStatus.INTERRUPTED,
            )
        elif isinstance(event, ResponseStarted):
            self._response_drafts[event.response_id] = _ResponseDraft(
                context=event.context,
                parent_item_id=self._response_parents.get(event.response_id),
                revision_metadata={
                    "input_id": event.input_id, "input_version": event.input_version,
                    "reply_version": event.reply_version,
                    "supersedes_response_id": event.supersedes_response_id,
                },
            )
        elif isinstance(event, DisplayContentDelta):
            self._draft_for(event.response_id, event.context).display_parts.append(event.delta)
        elif isinstance(event, SpokenContentDelta):
            self._draft_for(event.response_id, event.context).spoken_parts.append(event.delta)
        elif isinstance(event, ResponseCompleted):
            await self._settle_response(event, ConversationItemStatus.COMPLETED)
        elif isinstance(event, ResponseCancelled):
            await self._settle_response(event, ConversationItemStatus.CANCELLED)
        elif isinstance(event, ResponseFailed):
            await self._settle_response(event, ConversationItemStatus.FAILED)

        await self._events.put(event)

    async def _commit_user_transcript(self, event: InputTranscriptCompleted) -> None:
        item_id = self._stable_id(event.context, "user-input")
        self._pending_user_items[item_id] = event
        draft = ConversationItemDraft(
            item_id=item_id,
            context=event.context,
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="realtime-turn-controller",
            content=(TextContent(event.text),),
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            occurred_at=event.occurred_at,
            provider_metadata={
                "continuation_of_turn_id": event.continuation_of_turn_id,
                "transcript_revision": event.transcript_revision,
                "provider_endpoint_observed": event.provider_endpoint_observed,
                "input_id": event.input_id,
                "input_observation_id": event.input_observation_id,
                "input_version": event.input_version,
                "admission_reason": event.admission_reason,
                "endpoint_decision": event.endpoint_decision,
                "endpoint_source": event.endpoint_source,
                "input_relation": event.input_relation,
                "input_relation_source": event.input_relation_source,
                "related_turn_id": event.related_turn_id,
                "supersedes_unplayed_reply": event.supersedes_unplayed_reply,
            },
        )
        await self._send_internal(
            AppendItem(
                command_id=f"append:{item_id}",
                idempotency_key=f"append:{item_id}",
                context=event.context,
                draft=draft,
            )
        )

    async def _request_response_for_projected_user(self, event: ItemProjected) -> None:
        transcript = self._pending_user_items.pop(event.item_id, None)
        if transcript is None:
            return
        response_id = self._stable_id(transcript.context, "assistant-response")
        response_context = replace(transcript.context, response_id=response_id)
        output_item_id = self._stable_id(
            response_context,
            f"assistant-output:{response_id}",
        )
        self._response_parents[response_id] = event.item_id
        self._response_output_item_ids[response_id] = output_item_id
        await self._send_internal(
            RequestResponse(
                command_id=f"respond:{response_id}",
                idempotency_key=f"respond:{response_id}",
                context=response_context,
                response_id=response_id,
                minimum_thread_sequence=event.thread_sequence,
                output_item_id=output_item_id,
            )
        )

    def _draft_for(
        self, response_id: str, context: InteractionContext
    ) -> _ResponseDraft:
        draft = self._response_drafts.get(response_id)
        if draft is None:
            draft = _ResponseDraft(
                context=context,
                parent_item_id=self._response_parents.get(response_id),
            )
            self._response_drafts[response_id] = draft
        return draft

    async def _settle_response(
        self,
        event: ResponseCompleted | ResponseCancelled | ResponseFailed,
        status: ConversationItemStatus,
    ) -> None:
        if event.response_id in self._direct_delivery_responses:
            self._response_drafts.pop(event.response_id, None)
            return
        draft = self._response_drafts.pop(event.response_id, None)
        if draft is None:
            return
        display_text = "".join(draft.display_parts)
        spoken_text = "".join(draft.spoken_parts)
        semantic_text = display_text or spoken_text
        if not semantic_text:
            return
        item_id = self._response_output_item_ids.pop(
            event.response_id,
            self._stable_id(
                event.context,
                f"assistant-output:{event.response_id}",
            ),
        )
        metadata: dict[str, object] = {"response_id": event.response_id, **draft.revision_metadata}
        if isinstance(event, ResponseFailed):
            metadata["error"] = event.error
        elif isinstance(event, ResponseCancelled):
            metadata["reason"] = event.reason
        item_context = replace(event.context, response_id=event.response_id)
        item = ConversationItemDraft(
            item_id=item_id,
            context=item_context,
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=status,
            producer="realtime-turn-controller",
            content=(TextContent(semantic_text),),
            display=DisplayContent(display_text) if display_text else None,
            spoken=SpokenContent(spoken_text) if spoken_text else None,
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            parent_item_id=draft.parent_item_id,
            occurred_at=event.occurred_at,
            provider_metadata=metadata,
        )
        await self._send_internal(
            AppendItem(
                command_id=f"append:{item_id}",
                idempotency_key=f"append:{item_id}",
                context=item_context,
                draft=item,
            )
        )

    async def _settle_external_speech(
        self,
        *,
        speech_id: str,
        text: str,
        context: InteractionContext,
        occurred_at,
        status: ConversationItemStatus,
    ) -> None:
        draft = self._speech_drafts.pop(speech_id, None)
        if draft is None or not text:
            return
        if draft.context_policy is SpeechContextPolicy.NONE:
            return
        if (
            draft.context_policy is SpeechContextPolicy.AUTO
            and draft.source_item_id is not None
        ):
            return
        item_id = self._stable_id(context, f"external-speech:{speech_id}")
        item = ConversationItemDraft(
            item_id=item_id,
            context=context,
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=status,
            producer="realtime-external-speech",
            content=(TextContent(text),),
            spoken=SpokenContent(text),
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            parent_item_id=draft.source_item_id,
            occurred_at=occurred_at,
            provider_metadata={
                "speech_id": speech_id,
                "speech_context_policy": draft.context_policy.value,
            },
        )
        await self._send_internal(
            AppendItem(
                command_id=f"append:{item_id}",
                idempotency_key=f"append:{item_id}",
                context=context,
                draft=item,
            )
        )

    async def _send_internal(self, command: RealtimeCommand) -> None:
        await self._conversation.send(command)
        if self._observer is not None:
            self._observer.observe_command(command)

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._iterate_events()

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return is_output_deliverable(self._conversation, event)

    async def _iterate_events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if isinstance(event, _PumpStopped):
                if event.error is not None:
                    raise RuntimeError("realtime turn controller event pump failed") from event.error
                return
            if self.output_delivery_allowed(event):
                yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pump_task.cancel()
        try:
            await self._pump_task
        except asyncio.CancelledError:
            pass
        await self._conversation.close()
        await self._events.put(_PumpStopped())

    @staticmethod
    def _stable_id(context: InteractionContext, boundary: str) -> str:
        scope = JournalScope.from_context(context)
        identity = (
            f"urn:voiceagent:realtime:{scope.tenant_id}:{scope.user_id}:"
            f"{scope.thread_id}:{context.turn_id}:{context.generation}:{boundary}"
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
