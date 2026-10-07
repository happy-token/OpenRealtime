"""Production WebSocket composition owned by the Voice Session Runtime."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from server.conversation_journal import ConversationJournal, JournalScope
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.observability.log_context import bind_voice_session_log_context
from server.realtime.protocol import RealtimeCommand, RealtimeConversation, RealtimeEvent
from server.realtime.protocol.engine import (
    is_output_context_current,
    is_output_deliverable,
    is_sentence_permit_current,
)
from server.realtime.protocol.events import RealtimeCapabilityFailed
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.runtime import RealtimeRuntimeFactory
from server.realtime.transport.websocket import (
    ConfirmationDecisionHandler,
    InboundFallback,
    RealtimeWebSocketFrameBridge,
)
from server.tools.policy_gateway import PendingAuthorizationState
from server.transport.base import TransportAdapter
from server.transport.frames import (
    ConfirmationDecisionFrame,
    ConfirmationRequestedFrame,
    ConfirmationResolutionFrame,
    OutboundFrame,
    UserTextFrame,
    VoiceSessionEventTailFrame,
    VoiceSessionPhaseChangedFrame,
    VoiceSessionReadyFrame,
    VoiceSessionSnapshotFrame,
)
from server.voice_session.control_recovery import (
    AtomicVoiceSessionRecovery,
    ControlRecoveryState,
    JournalControlStateRestorer,
)
from server.voice_session.models import (
    VoiceSessionFailed,
    VoiceSessionFailureCode,
    VoiceSessionIdentity,
    VoiceSessionPhase,
    VoiceSessionPhaseChanged,
    VoiceSessionReady,
    VoiceSessionRecoveryFailed,
)
from server.voice_session.protocol import InputEpochStarted, VoiceSessionFailureFrame
from server.voice_session.runtime import (
    VoiceSessionAdmissionController,
    VoiceSessionConversationUnavailable,
    VoiceSessionRuntime,
)
from server.voice_session.speech_failure import provider_failure_frame

logger = logging.getLogger(__name__)


class PendingConfirmationAuthority(Protocol):
    async def pending_confirmation(
        self,
        confirmation_id: str,
    ) -> PendingAuthorizationState | None: ...


class AgentWorkRegistryRebuilder(Protocol):
    async def rebuild(self, identity: VoiceSessionIdentity) -> object: ...


class _ReconnectableConversation:
    """Keep bridge pumps alive while a quiesced provider conversation is replaced."""

    def __init__(self) -> None:
        self._current: RealtimeConversation | None = None
        self._generation = 0
        self._closed = False
        self._changed = asyncio.Condition()

    @property
    def current(self) -> RealtimeConversation | None:
        return self._current

    async def attach(self, conversation: RealtimeConversation) -> None:
        async with self._changed:
            if self._closed:
                raise RuntimeError("Realtime Conversation slot is closed")
            if self._current is not None:
                raise RuntimeError("Realtime Conversation slot is already occupied")
            self._current = conversation
            self._generation += 1
            self._changed.notify_all()

    async def send(self, command: RealtimeCommand) -> None:
        conversation = self._current
        if conversation is None:
            raise RuntimeError("Realtime Conversation is quiesced")
        await conversation.send(command)

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._events()

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit) -> bool:
        return not self._closed and is_sentence_permit_current(self._current, permit)

    def output_context_current(self, event: RealtimeEvent) -> bool:
        return self._current is not None and is_output_context_current(self._current, event)

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return self._current is not None and is_output_deliverable(self._current, event)

    async def _events(self) -> AsyncIterator[RealtimeEvent]:
        observed_generation = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(
                    lambda generation=observed_generation: (
                        self._closed or self._generation > generation
                    )
                )
                if self._closed:
                    return
                conversation = self._current
                observed_generation = self._generation
            assert conversation is not None
            async for event in conversation.events():
                yield event

    async def quiesce(self) -> None:
        async with self._changed:
            conversation, self._current = self._current, None
        if conversation is not None:
            await conversation.close()

    async def close(self) -> None:
        async with self._changed:
            if self._closed:
                return
            self._closed = True
            conversation, self._current = self._current, None
            self._changed.notify_all()
        if conversation is not None:
            await conversation.close()


class _ConversationFactory:
    def __init__(
        self,
        *,
        context: InteractionContext,
        runtime_factory: RealtimeRuntimeFactory,
        active_conversations: ActiveRealtimeConversations | None,
    ) -> None:
        self._context = context
        self._runtime_factory = runtime_factory
        self._active_conversations = active_conversations
        self.opened = asyncio.Event()
        self.conversation = _ReconnectableConversation()
        self._open_count = 0

    async def open(
        self, *, identity: VoiceSessionIdentity, profile: object
    ) -> RealtimeConversation:
        del identity
        try:
            delegate = await self._runtime_factory.open(
                context=self._context,
                profile=profile,
            )
        except Exception as error:
            raise VoiceSessionConversationUnavailable() from error
        if self._open_count > 0 and self._active_conversations is not None:
            self._active_conversations.suspend(
                context=self._context,
                conversation=delegate,
            )
        await self.conversation.attach(delegate)
        self._open_count += 1
        self.opened.set()
        return self.conversation


@dataclass(slots=True)
class _JournalRecovery:
    journal: ConversationJournal
    scope: JournalScope

    async def latest_sequence(self) -> int:
        after_sequence = 0
        while True:
            items = await self.journal.read(
                self.scope,
                after_sequence=after_sequence,
                limit=1000,
            )
            if not items:
                return after_sequence
            after_sequence = items[-1].sequence

    async def restore(self, *, target_thread_sequence: int) -> tuple[int, str]:
        after_sequence = 0
        digest = hashlib.sha256()
        while after_sequence < target_thread_sequence:
            items = await self.journal.read(
                self.scope,
                after_sequence=after_sequence,
                limit=min(1000, target_thread_sequence - after_sequence),
            )
            if not items:
                break
            for item in items:
                if item.sequence > target_thread_sequence:
                    break
                digest.update(f"{item.sequence}:{item.item_digest}\n".encode())
                after_sequence = item.sequence
        if after_sequence < target_thread_sequence:
            return after_sequence, ""
        return target_thread_sequence, digest.hexdigest()


@dataclass(slots=True)
class _EndpointControlRecoverySink:
    identity: VoiceSessionIdentity
    transport: TransportAdapter
    confirmation_authority: PendingConfirmationAuthority | None
    work_registry: AgentWorkRegistryRebuilder | None
    publish_resume_state: Callable[
        [ControlRecoveryState, tuple[str, ...]], Awaitable[None]
    ]
    confirmation_frame: ConfirmationRequestedFrame | None = None

    async def apply(
        self,
        *,
        idempotency_key: str,
        state: ControlRecoveryState,
    ) -> None:
        del idempotency_key
        active_work_refs = state.active_worker_ids
        if self.work_registry is not None:
            work_snapshot = await self.work_registry.rebuild(self.identity)
            worker_ids = getattr(work_snapshot, "worker_ids", None)
            if isinstance(worker_ids, tuple):
                active_work_refs = worker_ids
        pending = state.pending_confirmation
        if pending is not None:
            authority = self.confirmation_authority
            if authority is None:
                raise RuntimeError(
                    "pending confirmation cannot recover without its authority store"
                )
            stored = await authority.pending_confirmation(pending.confirmation_id)
            if stored is not None:
                authoritative = stored.pending
                if (
                    authoritative.context.tenant_id != self.identity.tenant_id
                    or authoritative.context.user_id != self.identity.user_id
                    or authoritative.context.device_id != self.identity.device_id
                    or authoritative.context.voice_session_id
                    != self.identity.voice_session_id
                    or authoritative.context.thread_id != self.identity.thread_id
                    or authoritative.action_digest != pending.action_digest
                    or authoritative.action_summary != pending.action_summary
                    or authoritative.required_channel.value != pending.required_channel
                    or authoritative.expires_at != pending.expires_at
                ):
                    raise ValueError(
                        "Journal confirmation does not match authorization authority"
                    )
                self.confirmation_frame = ConfirmationRequestedFrame(
                    confirmation_id=pending.confirmation_id,
                    action_digest=pending.action_digest,
                    summary=pending.action_summary,
                    required_channel=pending.required_channel,
                    expires_at=pending.expires_at,
                    generation=pending.generation,
                )
        await self.publish_resume_state(state, active_work_refs)

    async def publish(self) -> None:
        if self.confirmation_frame is not None:
            await self.transport.send(self.confirmation_frame)


class VoiceSessionWebSocketSession:
    """Keep one Realtime Conversation behind Voice Session startup/recovery barriers."""

    def __init__(
        self,
        *,
        identity: VoiceSessionIdentity,
        context: InteractionContext,
        profile: object,
        runtime_factory: RealtimeRuntimeFactory,
        journal: ConversationJournal,
        transport: TransportAdapter,
        admission: VoiceSessionAdmissionController,
        fast_resume_window_s: float = 5.0,
        event_tail_capacity: int = 256,
        recovery_deadline_s: float = 15.0,
        inbound_fallback: InboundFallback | None = None,
        confirmation_decision_handler: ConfirmationDecisionHandler | None = None,
        pending_confirmation_authority: PendingConfirmationAuthority | None = None,
        active_conversations: ActiveRealtimeConversations | None = None,
        agent_work_registry: AgentWorkRegistryRebuilder | None = None,
        initial_frames: tuple[OutboundFrame, ...] = (),
        provider_credential_sources: dict[str, str] | None = None,
        diagnostic_observer: Callable[[object], None] | None = None,
    ) -> None:
        self._identity = identity
        self._context = context
        self._profile = profile
        self._runtime_factory = runtime_factory
        self._transport = transport
        self._admission = admission
        self._fast_resume_window_s = fast_resume_window_s
        self._event_tail_capacity = event_tail_capacity
        self._recovery_deadline_s = recovery_deadline_s
        self._inbound_fallback = inbound_fallback
        self._confirmation_decision_handler = confirmation_decision_handler
        self._initial_frames = initial_frames
        self._provider_credential_sources = provider_credential_sources
        self._diagnostic_observer = diagnostic_observer
        self._journal_recovery = _JournalRecovery(
            journal=journal,
            scope=JournalScope.from_context(context),
        )
        self._control_restorer = JournalControlStateRestorer(
            identity=identity,
            journal=journal,
        )
        self._pending_confirmation_authority = pending_confirmation_authority
        self._active_conversations = active_conversations
        self._agent_work_registry = agent_work_registry
        self._runtime: VoiceSessionRuntime | None = None
        self._conversation: RealtimeConversation | None = None
        self._bridge: RealtimeWebSocketFrameBridge | None = None
        self._closed = False

    async def run(self) -> None:
        with bind_voice_session_log_context(self._identity.voice_session_id):
            await self._run()

    async def _run(self) -> None:
        conversations = _ConversationFactory(
            context=self._context,
            runtime_factory=self._runtime_factory,
            active_conversations=self._active_conversations,
        )
        runtime = VoiceSessionRuntime(
            identity=self._identity,
            profile=self._profile,
            admission=self._admission,
            conversations=conversations,
            fast_resume_window_s=self._fast_resume_window_s,
            event_tail_capacity=self._event_tail_capacity,
            recovery_deadline_s=self._recovery_deadline_s,
        )
        self._runtime = runtime
        start_task = asyncio.create_task(
            runtime.start(),
            name=f"voice-session-start-{self._identity.voice_session_id}",
        )
        voice_events = asyncio.create_task(
            self._pump_voice_events(runtime),
            name="voice-session-lifecycle-events",
        )
        opened_wait = asyncio.create_task(conversations.opened.wait())
        opened_done, _ = await asyncio.wait(
            (start_task, opened_wait),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if start_task in opened_done and not conversations.opened.is_set():
            await start_task
            await asyncio.sleep(0)
            voice_events.cancel()
            await asyncio.gather(voice_events, return_exceptions=True)
            return
        opened_wait.cancel()
        await asyncio.gather(opened_wait, return_exceptions=True)
        conversation = conversations.conversation
        self._conversation = conversation
        bridge = RealtimeWebSocketFrameBridge(
            context=self._context,
            conversation=conversation,
            transport=self._transport,
            precise_output_stop=True,
            diagnostic_observer=self._diagnostic_observer,
            inbound_fallback=self._inbound_fallback,
            input_epoch_started=self._accept_input_epoch,
            confirmation_decision_handler=(
                self._accept_confirmation_decision
                if self._confirmation_decision_handler is not None
                else None
            ),
        )
        self._bridge = bridge
        for frame in self._initial_frames:
            await self._transport.send(frame)
        tasks = (
            asyncio.create_task(self._pump_inbound(bridge), name="voice-session-inbound"),
            asyncio.create_task(
                self._pump_realtime_events(conversation, bridge),
                name="voice-session-realtime-events",
            ),
            voice_events,
            asyncio.create_task(bridge.wait_for_output_failure(), name="voice-session-output-failure"),
        )
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Voice Session endpoint failed: session=%s",
                self._identity.voice_session_id,
            )
            try:
                await self._transport.send(
                    VoiceSessionFailureFrame(
                        code=VoiceSessionFailureCode.INTERNAL_ERROR.value,
                        phase=runtime.phase.value,
                        retryable=False,
                        session_disposition="close",
                        safe_message="语音会话发生内部错误，请重新连接后重试。",
                    )
                )
            except Exception:
                logger.exception(
                    "Voice Session internal failure could not reach client: session=%s",
                    self._identity.voice_session_id,
                )
        finally:
            self._closed = True
            bridge.begin_close()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if not start_task.done():
                start_task.cancel()
            await asyncio.gather(*tasks, start_task, return_exceptions=True)
            await bridge.close()
            await runtime.stop(reason="endpoint_closed")
            finalize_diagnostics = getattr(self._diagnostic_observer, "close", None)
            if finalize_diagnostics is not None:
                finalize_diagnostics()

    async def detached(self) -> None:
        runtime = self._runtime
        if (
            runtime is not None
            and not self._closed
            and runtime.phase is VoiceSessionPhase.ACTIVE
        ):
            bridge = self._bridge
            conversation = self._conversation
            active_conversations = self._active_conversations
            if active_conversations is not None and conversation is not None:
                delegate = conversation.current
                if delegate is not None:
                    active_conversations.suspend(
                        context=self._context,
                        conversation=delegate,
                    )
            if bridge is not None:
                await bridge.handle_detached()
            await runtime.detached()

    async def _accept_confirmation_decision(
        self,
        frame: ConfirmationDecisionFrame,
    ) -> None:
        runtime = self._runtime
        if runtime is None or runtime.phase is not VoiceSessionPhase.ACTIVE:
            await self._transport.send(
                ConfirmationResolutionFrame(
                    confirmation_id=frame.confirmation_id,
                    applied=False,
                    approved=frame.approved,
                    success=False,
                    message="会话恢复后会重新显示待确认操作，请届时再决定。",
                    error="confirmation_restatement_required",
                )
            )
            return
        handler = self._confirmation_decision_handler
        assert handler is not None
        await handler(frame)

    async def _accept_input_epoch(self, frame: InputEpochStarted) -> None:
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("Voice Session Runtime has not started")
        if self._inbound_fallback is not None:
            await self._inbound_fallback(frame)
        input_epoch = frame.input_epoch
        if runtime.phase is VoiceSessionPhase.STARTING:
            await runtime.mark_client_audio_ready(input_epoch=input_epoch)
            return
        if runtime.phase is VoiceSessionPhase.ACTIVE:
            await runtime.replace_active_input_epoch(input_epoch=input_epoch)
            return
        if runtime.phase is not VoiceSessionPhase.RECONNECTING:
            raise RuntimeError("input epoch arrived outside a Voice Session barrier")
        target = await self._journal_recovery.latest_sequence()
        recovery_sink = _EndpointControlRecoverySink(
            identity=self._identity,
            transport=self._transport,
            confirmation_authority=self._pending_confirmation_authority,
            work_registry=self._agent_work_registry,
            publish_resume_state=lambda state, active_work_refs: (
                self._publish_semantic_resume(
                    runtime,
                    target_thread_sequence=target,
                    state=state,
                    active_work_refs=active_work_refs,
                )
            ),
        )
        recovery = AtomicVoiceSessionRecovery(
            identity=self._identity,
            context_restorer=self._journal_recovery,
            control_restorer=self._control_restorer,
            sink=recovery_sink,
        )
        resume_task = asyncio.create_task(
            runtime.resume(
                target_thread_sequence=target,
                input_epoch=input_epoch,
                recovery=recovery,
            )
        )
        await asyncio.sleep(0)
        await runtime.mark_client_audio_ready(input_epoch=input_epoch)
        await resume_task
        if runtime.phase is VoiceSessionPhase.ACTIVE:
            conversation = self._conversation
            active_conversations = self._active_conversations
            if active_conversations is not None and conversation is not None:
                delegate = conversation.current
                if delegate is not None:
                    active_conversations.resume(
                        context=self._context,
                        conversation=delegate,
                    )
            await recovery_sink.publish()

    async def _publish_semantic_resume(
        self,
        runtime: VoiceSessionRuntime,
        *,
        target_thread_sequence: int,
        state: ControlRecoveryState,
        active_work_refs: tuple[str, ...],
    ) -> None:
        hello = getattr(self._transport, "client_hello", None)
        last_session_sequence = (
            hello.last_session_sequence if hello is not None else 0
        )
        plan = runtime.plan_semantic_resume(
            last_session_sequence=last_session_sequence,
            journal_sequence=target_thread_sequence,
            generation=self._context.generation,
            active_work_refs=active_work_refs,
            pending_confirmation_id=(
                state.pending_confirmation.confirmation_id
                if state.pending_confirmation is not None
                else None
            ),
            playback_generation=(
                hello.playback.generation
                if hello is not None and hello.playback is not None
                else None
            ),
            played_position_samples=(
                hello.playback.played_position_samples
                if hello is not None and hello.playback is not None
                else None
            ),
        )
        if plan.snapshot is not None:
            snapshot = plan.snapshot
            await self._transport.send(
                VoiceSessionSnapshotFrame(
                    session_sequence=snapshot.session_sequence,
                    journal_sequence=snapshot.journal_sequence,
                    generation=snapshot.generation,
                    phase=snapshot.phase.value,
                    active_work_refs=snapshot.active_work_refs,
                    pending_confirmation_id=snapshot.pending_confirmation_id,
                    playback_generation=snapshot.playback_generation,
                    played_position_samples=snapshot.played_position_samples,
                )
            )
            return
        visible_events = []
        for event in plan.events:
            if isinstance(event, VoiceSessionPhaseChanged):
                visible_events.append(
                    VoiceSessionPhaseChangedFrame(
                        session_sequence=event.session_sequence,
                        from_phase=event.from_phase.value,
                        to_phase=event.to_phase.value,
                    )
                )
            elif isinstance(event, VoiceSessionReady):
                visible_events.append(
                    VoiceSessionReadyFrame(
                        session_sequence=event.session_sequence,
                        input_epoch=event.input_epoch,
                    )
                )
        through_sequence = (
            plan.events[-1].session_sequence
            if plan.events
            else plan.resume_from_sequence
        )
        await self._transport.send(
            VoiceSessionEventTailFrame(
                resume_from_sequence=plan.resume_from_sequence,
                through_sequence=through_sequence,
                events=tuple(visible_events),
            )
        )

    async def _pump_inbound(self, bridge: RealtimeWebSocketFrameBridge) -> None:
        async for frame in self._transport.receive():
            runtime = self._runtime
            if (
                isinstance(frame, UserTextFrame)
                and runtime is not None
                and runtime.phase is VoiceSessionPhase.STARTING
            ):
                await runtime.mark_client_audio_ready(
                    input_epoch=f"text-only:{self._identity.voice_session_id}"
                )
            await bridge.handle_inbound(frame)

    async def _pump_realtime_events(
        self,
        conversation: RealtimeConversation,
        bridge: RealtimeWebSocketFrameBridge,
    ) -> None:
        async for event in conversation.events():
            if (
                self._provider_credential_sources is not None
                and isinstance(event, RealtimeCapabilityFailed)
                and event.capability in {"asr", "tts", "brain"}
            ):
                await self._transport.send(provider_failure_frame(
                    event.capability,
                    self._provider_credential_sources[event.capability],
                    event.error,
                ))
                await self._transport.close()
                return
            await bridge.handle_event(event)

    async def _pump_voice_events(self, runtime: VoiceSessionRuntime) -> None:
        async for event in runtime.events():
            if self._diagnostic_observer is not None:
                self._diagnostic_observer(event)
            if isinstance(event, VoiceSessionPhaseChanged):
                await self._transport.send(
                    VoiceSessionPhaseChangedFrame(
                        session_sequence=event.session_sequence,
                        from_phase=event.from_phase.value,
                        to_phase=event.to_phase.value,
                    )
                )
            elif isinstance(event, VoiceSessionReady):
                await self._transport.send(
                    VoiceSessionReadyFrame(
                        session_sequence=event.session_sequence,
                        input_epoch=event.input_epoch,
                    )
                )
            elif isinstance(event, (VoiceSessionFailed, VoiceSessionRecoveryFailed)):
                await self._transport.send(
                    VoiceSessionFailureFrame(
                        error_id=event.event_id,
                        code=event.code.value,
                        phase=(
                            event.phase.value
                            if isinstance(event, VoiceSessionFailed)
                            else VoiceSessionPhase.RECONNECTING.value
                        ),
                        retryable=event.retryable,
                        retry_after_ms=event.retry_after_ms,
                        session_disposition=event.session_disposition.value,
                        safe_message=event.safe_message,
                    )
                )
