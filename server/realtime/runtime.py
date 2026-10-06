"""Application composition root for one managed Realtime Conversation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from server.conversation_journal import ConversationJournal, JournalScope
from server.core.interaction_context import InteractionContext
from server.realtime.control_plane import RealtimeTurnController
from server.realtime.delegation_controller import (
    AgentTaskSubmitter,
    DelegationRequestFactory,
    RealtimeDelegationController,
)
from server.realtime.journaled import (
    JournalCommittedProjector,
    JournaledRealtimeConversation,
)
from server.realtime.observability import RealtimeObserver
from server.realtime.protocol.commands import (
    CancelResponse,
    CancelSpeech,
    DeliverItem,
    DeliveryMode,
    ProjectCommittedItem,
    RealtimeCommand,
    RequestResponse,
    StartSpeech,
)
from server.realtime.protocol.engine import (
    VERSIONED_OUTPUT_EVENTS,
    RealtimeConversation,
    RealtimeEngine,
    is_output_deliverable,
)
from server.realtime.protocol.events import (
    ItemProjected,
    RealtimeCapabilityFailed,
    RealtimeEvent,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechAudioCompleted,
    SpeechCancelled,
    SpeechStarted,
)
from server.realtime.recovery import ProfileFailureRecovery, RealtimeFailureRecovery
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.speech import (
    SpeechDeliveryStore,
    project_assistant_context,
)
from server.realtime.tool_controller import RealtimeToolController
from server.tools.control import ToolControlHandler

_CLOSED = object()
logger = logging.getLogger(__name__)


class RealtimeRuntimeFactory:
    """Open the Engine and apply the server-owned control-plane decorators."""

    def __init__(
        self,
        *,
        engine: RealtimeEngine | None = None,
        engine_resolver: Callable[[object], RealtimeEngine] | None = None,
        failure_recovery: RealtimeFailureRecovery | None = None,
        journal: ConversationJournal,
        speech_deliveries: SpeechDeliveryStore | None = None,
        active_conversations: ActiveRealtimeConversations,
        tool_control_handler_factory: Callable[[], ToolControlHandler] | None = None,
        agent_task_supervisor: AgentTaskSubmitter | None = None,
        delegation_request_factory: DelegationRequestFactory | None = None,
        observer: RealtimeObserver | None = None,
    ) -> None:
        if (engine is None) == (engine_resolver is None):
            raise ValueError("configure exactly one of engine or engine_resolver")
        if (agent_task_supervisor is None) != (delegation_request_factory is None):
            raise ValueError(
                "configure agent_task_supervisor and delegation_request_factory together"
            )
        self._engine = engine
        self._engine_resolver = engine_resolver
        self._failure_recovery = failure_recovery or ProfileFailureRecovery()
        self._journal = journal
        self._speech_deliveries = speech_deliveries
        self._active_conversations = active_conversations
        self._tool_control_handler_factory = tool_control_handler_factory
        self._agent_task_supervisor = agent_task_supervisor
        self._delegation_request_factory = delegation_request_factory
        self._observer = observer

    async def open(
        self, *, context: InteractionContext, profile
    ) -> ManagedRealtimeConversation:
        conversation, replayed_item_ids = await self._open_delegate(
            context=context,
            profile=profile,
        )
        try:
            managed = ManagedRealtimeConversation(
                context=context,
                profile=profile,
                conversation=conversation,
                replayed_item_ids=replayed_item_ids,
                factory=self,
                failure_recovery=self._failure_recovery,
                active_conversations=self._active_conversations,
                observer=self._observer,
            )
            self._active_conversations.register(
                context=context,
                conversation=managed,
            )
            return managed
        except Exception:
            await conversation.close()
            raise

    async def _open_delegate(
        self,
        *,
        context: InteractionContext,
        profile,
    ) -> tuple[RealtimeConversation, set[str]]:
        engine = (
            self._engine_resolver(profile)
            if self._engine_resolver is not None
            else self._engine
        )
        assert engine is not None
        engine_conversation = await engine.open(context=context, profile=profile)
        try:
            replayed_item_ids, projected_through = await self._replay_journal(
                context=context,
                conversation=engine_conversation,
            )
            committed_projection = JournalCommittedProjector(
                context=context,
                journal=self._journal,
                engine_conversation=engine_conversation,
                projected_through=projected_through,
            )
            journaled = JournaledRealtimeConversation(
                context=context,
                journal=self._journal,
                engine_conversation=engine_conversation,
                committed_projection=committed_projection,
            )
            controlled: RealtimeConversation = journaled
            if self._tool_control_handler_factory is not None:
                controlled = RealtimeToolController(
                    context=context,
                    conversation=journaled,
                    committed_projection=committed_projection,
                    tool_control_handler_factory=self._tool_control_handler_factory,
                )
            if self._agent_task_supervisor is not None:
                assert self._delegation_request_factory is not None
                controlled = RealtimeDelegationController(
                    context=context,
                    conversation=controlled,
                    committed_projection=committed_projection,
                    supervisor=self._agent_task_supervisor,
                    request_factory=self._delegation_request_factory,
                )
            return (
                RealtimeTurnController(
                    context=context,
                    conversation=controlled,
                    observer=self._observer,
                ),
                replayed_item_ids,
            )
        except Exception:
            await engine_conversation.close()
            raise

    async def _replay_journal(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
    ) -> tuple[set[str], int]:
        scope = JournalScope.from_context(context)
        after_sequence = 0
        replayed_item_ids: set[str] = set()
        while True:
            items = await self._journal.read(
                scope,
                after_sequence=after_sequence,
                limit=1000,
            )
            if not items:
                return replayed_item_ids, after_sequence
            for item in items:
                projected_item = item
                if self._speech_deliveries is not None:
                    delivery = await self._speech_deliveries.latest_for_item(
                        item.item_id
                    )
                    if delivery is not None:
                        content = project_assistant_context(item, delivery)
                        projected_item = replace(item, content=content)
                await conversation.send(
                    ProjectCommittedItem(
                        command_id=f"restore:{item.item_id}:{item.sequence}",
                        idempotency_key=f"restore:{item.item_id}:{item.sequence}",
                        context=context,
                        item=projected_item,
                    )
                )
                replayed_item_ids.add(item.item_id)
            after_sequence = items[-1].sequence


class ManagedRealtimeConversation:
    """Stable public handle around a replaceable stateful engine session.

    Reconfiguration is a barrier: public sends are serialized, active output is
    cancelled, the old capability sessions are closed, and the Journal is
    replayed before the replacement accepts commands.
    """

    def __init__(
        self,
        *,
        context: InteractionContext,
        profile,
        conversation: RealtimeConversation,
        replayed_item_ids: set[str],
        factory: RealtimeRuntimeFactory,
        failure_recovery: RealtimeFailureRecovery | None,
        active_conversations: ActiveRealtimeConversations,
        observer: RealtimeObserver | None,
    ) -> None:
        self._context = context
        self._profile = profile
        self._conversation = conversation
        self._replayed_item_ids = replayed_item_ids
        self._factory = factory
        self._failure_recovery = failure_recovery
        self._active_conversations = active_conversations
        self._observer = observer
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._active_response_ids: set[str] = set()
        self._active_speech_ids: set[str] = set()
        self._outputs_quiet = asyncio.Event()
        self._outputs_quiet.set()
        self._event_sequence = 0
        self._closed = False
        self._recovery_task: asyncio.Task[None] | None = None
        self._event_pump = self._start_event_pump(conversation)

    async def send(self, command: RealtimeCommand) -> None:
        async with self._send_lock:
            if self._closed:
                raise RuntimeError("managed realtime conversation is closed")
            response_id = self._response_id_started_by(command)
            speech_id = command.speech_id if isinstance(command, StartSpeech) else None
            self._mark_output_started(response_id=response_id, speech_id=speech_id)
            try:
                await self._conversation.send(command)
            except Exception:
                self._mark_output_finished(response_id=response_id, speech_id=speech_id)
                raise
            if self._observer is not None:
                try:
                    self._observer.observe_command(command)
                except Exception:
                    logger.exception("Realtime command diagnostics projection failed")

    async def reconfigure(self, *, profile) -> None:
        """Replace all stateful capability sessions behind one atomic barrier."""

        async with self._send_lock:
            if self._closed:
                raise RuntimeError("managed realtime conversation is closed")
            previous_profile = self._profile
            previous = self._conversation
            previous_pump = self._event_pump
            await self._cancel_active_outputs(previous)
            if self._active_response_ids or self._active_speech_ids:
                await self._outputs_quiet.wait()
            await previous.close()
            await previous_pump
            try:
                replacement, replayed_item_ids = await self._factory._open_delegate(
                    context=self._context,
                    profile=profile,
                )
            except Exception as reconfiguration_error:
                try:
                    replacement, replayed_item_ids = await self._factory._open_delegate(
                        context=self._context,
                        profile=previous_profile,
                    )
                except Exception as rollback_error:  # noqa: BLE001 - preserve both failures
                    self._closed = True
                    self._active_conversations.unregister(
                        context=self._context,
                        conversation=self,
                    )
                    await self._events.put(_CLOSED)
                    raise ExceptionGroup(
                        "Realtime reconfiguration and rollback both failed",
                        [reconfiguration_error, rollback_error],
                    ) from reconfiguration_error
                self._conversation = replacement
                self._replayed_item_ids = replayed_item_ids
                self._event_pump = self._start_event_pump(replacement)
                raise
            self._conversation = replacement
            self._profile = profile
            self._replayed_item_ids = replayed_item_ids
            self._event_pump = self._start_event_pump(replacement)

    async def _cancel_active_outputs(self, conversation: RealtimeConversation) -> None:
        for response_id in tuple(self._active_response_ids):
            try:
                await conversation.send(
                    CancelResponse(
                        command_id=f"reconfigure:cancel-response:{response_id}",
                        idempotency_key=f"reconfigure:cancel-response:{response_id}",
                        context=replace(self._context, response_id=response_id),
                        response_id=response_id,
                        reason="reconfiguration",
                    )
                )
            except ValueError as error:
                if "not active" not in str(error):
                    raise
                self._mark_output_finished(response_id=response_id)
        for speech_id in tuple(self._active_speech_ids):
            try:
                await conversation.send(
                    CancelSpeech(
                        command_id=f"reconfigure:cancel-speech:{speech_id}",
                        idempotency_key=f"reconfigure:cancel-speech:{speech_id}",
                        context=self._context,
                        speech_id=speech_id,
                        reason="reconfiguration",
                    )
                )
            except ValueError as error:
                if "not active" not in str(error):
                    raise
                self._mark_output_finished(speech_id=speech_id)

    def _start_event_pump(
        self, conversation: RealtimeConversation
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            self._pump_events(conversation),
            name=f"managed-realtime-events-{self._context.voice_session_id}",
        )

    async def _pump_events(self, conversation: RealtimeConversation) -> None:
        try:
            async for event in conversation.events():
                self._observe_terminal(event)
                if self._observer is not None:
                    try:
                        self._observer.observe_event(event)
                    except Exception:
                        logger.exception("Realtime event diagnostics projection failed")
                if (
                    isinstance(event, ItemProjected)
                    and event.item_id in self._replayed_item_ids
                ):
                    self._replayed_item_ids.remove(event.item_id)
                    continue
                await self._publish(event, origin=conversation)
                if isinstance(event, RealtimeCapabilityFailed):
                    self._schedule_recovery(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - convert delegate failure to protocol
            self._active_response_ids.clear()
            self._active_speech_ids.clear()
            self._outputs_quiet.set()
            await self._publish(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=self._context,
                    conversation_sequence=1,
                    occurred_at=datetime.now(UTC),
                    capability="managed_runtime_event_pump",
                    error=f"{type(error).__name__}: {error}",
                )
            )

    async def _publish(self, event: RealtimeEvent, *, origin: RealtimeConversation | None = None) -> None:
        self._event_sequence += 1
        await self._events.put((origin or self._conversation,
                               replace(event, conversation_sequence=self._event_sequence)))

    def _schedule_recovery(self, event: RealtimeCapabilityFailed) -> None:
        if self._failure_recovery is None or self._closed:
            return
        if self._recovery_task is not None and not self._recovery_task.done():
            return
        self._recovery_task = asyncio.create_task(
            self._recover_from(event),
            name=f"realtime-recovery-{self._context.voice_session_id}",
        )

    async def _recover_from(self, event: RealtimeCapabilityFailed) -> None:
        try:
            profile = await self._failure_recovery.recovery_profile(
                current_profile=self._profile,
                event=event,
            )
            if profile is not None and not self._closed:
                await self.reconfigure(profile=profile)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - recovery failure is observable
            if self._closed:
                return
            await self._publish(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=self._context,
                    conversation_sequence=1,
                    occurred_at=datetime.now(UTC),
                    capability="runtime_recovery",
                    error=f"{type(error).__name__}: {error}",
                )
            )

    def _observe_terminal(self, event: RealtimeEvent) -> None:
        if isinstance(event, ResponseStarted):
            self._mark_output_started(response_id=event.response_id)
        elif isinstance(event, SpeechStarted):
            self._mark_output_started(speech_id=event.speech_id)
        elif isinstance(event, (ResponseCompleted, ResponseCancelled, ResponseFailed)):
            self._mark_output_finished(response_id=event.response_id)
        elif isinstance(event, (SpeechAudioCompleted, SpeechCancelled)):
            self._mark_output_finished(speech_id=event.speech_id)

    def _mark_output_started(
        self,
        *,
        response_id: str | None = None,
        speech_id: str | None = None,
    ) -> None:
        if response_id is not None:
            self._active_response_ids.add(response_id)
        if speech_id is not None:
            self._active_speech_ids.add(speech_id)
        if response_id is not None or speech_id is not None:
            self._outputs_quiet.clear()

    def _mark_output_finished(
        self,
        *,
        response_id: str | None = None,
        speech_id: str | None = None,
    ) -> None:
        if response_id is not None:
            self._active_response_ids.discard(response_id)
        if speech_id is not None:
            self._active_speech_ids.discard(speech_id)
        if not self._active_response_ids and not self._active_speech_ids:
            self._outputs_quiet.set()

    @staticmethod
    def _response_id_started_by(command: RealtimeCommand) -> str | None:
        if isinstance(command, RequestResponse):
            return command.response_id
        if isinstance(command, DeliverItem) and command.mode in {
            DeliveryMode.MODEL_RESPONSE,
            DeliveryMode.SPEECH,
        }:
            return f"delivery:{command.delivery_id}"
        return None

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._iterate_events()

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return is_output_deliverable(self._conversation, event)

    async def _iterate_events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            origin, typed_event = cast(tuple[RealtimeConversation, RealtimeEvent], event)
            if origin is not self._conversation and isinstance(typed_event, VERSIONED_OUTPUT_EVENTS):
                continue
            if is_output_deliverable(origin, typed_event):
                yield typed_event

    async def close(self) -> None:
        async with self._send_lock:
            if self._closed:
                return
            self._closed = True
            try:
                recovery_task = self._recovery_task
                current_task = asyncio.current_task()
                if (
                    recovery_task is not None
                    and recovery_task is not current_task
                    and not recovery_task.done()
                ):
                    recovery_task.cancel()
                    await asyncio.gather(recovery_task, return_exceptions=True)
                await self._conversation.close()
                await self._event_pump
            finally:
                self._active_conversations.unregister(
                    context=self._context,
                    conversation=self,
                )
                await self._events.put(_CLOSED)
