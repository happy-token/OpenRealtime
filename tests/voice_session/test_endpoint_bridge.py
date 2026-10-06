from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from websockets.exceptions import ConnectionClosedError

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    InMemoryConversationJournal,
    StructuredContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.registry import ActiveRealtimeConversations
from server.transport.frames import (
    ConfirmationDecisionFrame,
    ConfirmationRequestedFrame,
    ConfirmationResolutionFrame,
    SessionHelloFrame,
    UserTextFrame,
    VoiceSessionEventTailFrame,
    VoiceSessionPhaseChangedFrame,
    VoiceSessionReadyFrame,
    VoiceSessionSnapshotFrame,
)
from server.transport.plugins.websocket import WebSocketTransportAdapter
from server.voice_session.admission import LocalVoiceSessionAdmissionController
from server.voice_session.endpoint_bridge import VoiceSessionWebSocketSession
from server.voice_session.models import VoiceSessionIdentity
from server.voice_session.protocol import (
    AudioFormat,
    DeviceCaptureProfile,
    InputEpochStarted,
    VoiceSessionFailureFrame,
)


class WaitingConversation:
    def __init__(self) -> None:
        self.closed = False
        self._closed = asyncio.Event()

    async def send(self, command) -> None:
        del command

    async def events(self):
        await self._closed.wait()
        if False:
            yield None

    async def close(self) -> None:
        self.closed = True
        self._closed.set()


class RecordingRuntimeFactory:
    def __init__(self) -> None:
        self.conversation = WaitingConversation()

    async def open(self, *, context, profile):
        del context, profile
        return self.conversation


class ReopeningRuntimeFactory:
    def __init__(self) -> None:
        self.conversations: list[WaitingConversation] = []

    async def open(self, *, context, profile):
        del context, profile
        conversation = WaitingConversation()
        self.conversations.append(conversation)
        return conversation


class EpochTransport:
    def __init__(self) -> None:
        profile = DeviceCaptureProfile()
        self._frame = InputEpochStarted(
            input_epoch="input-1",
            format=AudioFormat(format_id="browser-pcm16"),
            requested_profile=profile,
            effective_profile=profile,
        )
        self.sent = []
        self._closed = asyncio.Event()

    async def receive(self):
        yield self._frame
        await self._closed.wait()

    async def send(self, frame) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self._closed.set()


class ExplodingEpochTransport(EpochTransport):
    async def receive(self):
        yield self._frame
        await asyncio.sleep(0)
        raise RuntimeError("private provider detail")


class AbruptWebSocketConnection:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_code = 1006

    async def __aiter__(self):
        yield input_epoch("input-1").model_dump_json()
        raise ConnectionClosedError(None, None)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        pass


class QueuedEpochTransport:
    def __init__(self) -> None:
        self.frames: asyncio.Queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.client_hello = None

    async def receive(self):
        while not self.closed:
            frame = await self.frames.get()
            if frame is None:
                return
            yield frame

    async def send(self, frame) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True
        await self.frames.put(None)


def input_epoch(epoch: str) -> InputEpochStarted:
    profile = DeviceCaptureProfile()
    return InputEpochStarted(
        input_epoch=epoch,
        format=AudioFormat(format_id="browser-pcm16"),
        requested_profile=profile,
        effective_profile=profile,
    )


async def test_production_endpoint_releases_audio_only_after_runtime_barriers() -> None:
    transport = EpochTransport()
    runtime_factory = RecordingRuntimeFactory()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )
    observed_input_epochs = []

    async def observe_auxiliary_frame(frame) -> None:
        observed_input_epochs.append(frame)

    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=InteractionContext(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
            turn_id="turn-1",
            generation=1,
        ),
        profile="cascaded-default",
        runtime_factory=runtime_factory,
        journal=InMemoryConversationJournal(),
        transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
        inbound_fallback=observe_auxiliary_frame,
    )

    run_task = asyncio.create_task(endpoint.run())
    for _ in range(100):
        if any(isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent):
            break
        await asyncio.sleep(0)

    phases = [
        frame.to_phase
        for frame in transport.sent
        if isinstance(frame, VoiceSessionPhaseChangedFrame)
    ]
    ready = next(
        frame for frame in transport.sent if isinstance(frame, VoiceSessionReadyFrame)
    )
    assert phases[:2] == ["starting", "active"]
    assert ready.input_epoch == "input-1"
    assert ready.session_sequence > 1
    assert observed_input_epochs == [transport._frame]

    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)
    assert runtime_factory.conversation.closed is True


async def test_text_input_activates_session_without_microphone_epoch() -> None:
    transport = QueuedEpochTransport()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-text-only",
        thread_id="thread-1",
    )
    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=InteractionContext(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
            turn_id="turn-1",
            generation=1,
        ),
        profile="cascaded-default",
        runtime_factory=RecordingRuntimeFactory(),
        journal=InMemoryConversationJournal(),
        transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
    )
    run_task = asyncio.create_task(endpoint.run())
    try:
        await transport.frames.put(UserTextFrame(text="你好"))
        for _ in range(100):
            if any(isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent):
                break
            await asyncio.sleep(0)
        ready = next(
            frame for frame in transport.sent if isinstance(frame, VoiceSessionReadyFrame)
        )
        assert ready.input_epoch == "text-only:voice-text-only"
        assert endpoint._runtime.phase.value == "active"
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_endpoint_sanitizes_unhandled_runtime_failure() -> None:
    transport = ExplodingEpochTransport()
    runtime_factory = RecordingRuntimeFactory()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-internal-error",
        thread_id="thread-1",
    )
    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=InteractionContext(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
            turn_id="turn-1",
            generation=1,
        ),
        profile="cascaded-default",
        runtime_factory=runtime_factory,
        journal=InMemoryConversationJournal(),
        transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
    )

    await endpoint.run()

    failure = next(
        frame for frame in transport.sent if isinstance(frame, VoiceSessionFailureFrame)
    )
    assert failure.code == "internal_error"
    assert failure.retryable is False
    assert failure.session_disposition == "close"
    assert "private provider detail" not in failure.safe_message


async def test_abrupt_websocket_close_does_not_report_internal_error() -> None:
    connection = AbruptWebSocketConnection()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-disconnected",
        thread_id="thread-1",
    )
    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=InteractionContext(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
            turn_id="turn-1",
            generation=1,
        ),
        profile="cascaded-default",
        runtime_factory=RecordingRuntimeFactory(),
        journal=InMemoryConversationJournal(),
        transport=WebSocketTransportAdapter(connection),
        admission=LocalVoiceSessionAdmissionController(),
    )

    await asyncio.wait_for(endpoint.run(), 1)

    sent_frames = [json.loads(message) for message in connection.sent]
    assert any(frame.get("type") == "voice_session_ready" for frame in sent_frames)
    assert not any(
        frame.get("type") == "voice_session_failure" and frame.get("code") == "internal_error"
        for frame in sent_frames
    )


async def test_reconnect_barrier_restates_authoritative_pending_confirmation() -> None:
    transport = QueuedEpochTransport()
    runtime_factory = RecordingRuntimeFactory()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )
    context = InteractionContext(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        device_id=identity.device_id,
        voice_session_id=identity.voice_session_id,
        thread_id=identity.thread_id,
        turn_id="turn-2",
        generation=2,
        call_id="call-1",
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    digest = "a" * 64
    journal = InMemoryConversationJournal()
    await journal.append(
        ConversationItemDraft(
            item_id="confirmation-requested-1",
            context=context,
            kind=ConversationItemKind.CONFIRMATION_REQUESTED,
            status=ConversationItemStatus.COMMITTED,
            producer="test",
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            content=(
                StructuredContent(
                    {
                        "confirmation_id": "confirmation-1",
                        "action_digest": digest,
                        "action_summary": "删除文件 A（不可撤销）",
                        "required_channel": "strong",
                        "expires_at": expires_at.isoformat(),
                    }
                ),
            ),
        )
    )

    class Authority:
        async def pending_confirmation(self, confirmation_id: str):
            assert confirmation_id == "confirmation-1"
            return SimpleNamespace(
                pending=SimpleNamespace(
                    context=context,
                    action_digest=digest,
                    action_summary="删除文件 A（不可撤销）",
                    required_channel=SimpleNamespace(value="strong"),
                    expires_at=expires_at,
                )
            )

    accepted_decisions = []

    async def handle_confirmation(frame) -> None:
        accepted_decisions.append(frame)

    active_conversations = ActiveRealtimeConversations()
    active_conversations.register(
        context=context,
        conversation=runtime_factory.conversation,
    )

    class WorkRegistry:
        def __init__(self) -> None:
            self.rebuilt = []

        async def rebuild(self, recovered_identity):
            self.rebuilt.append(recovered_identity)

    work_registry = WorkRegistry()

    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=context,
        profile="cascaded-default",
        runtime_factory=runtime_factory,
        journal=journal,
        transport=transport,
        confirmation_decision_handler=handle_confirmation,
        pending_confirmation_authority=Authority(),
        active_conversations=active_conversations,
        agent_work_registry=work_registry,
        admission=LocalVoiceSessionAdmissionController(),
    )
    run_task = asyncio.create_task(endpoint.run())
    await transport.frames.put(input_epoch("input-1"))
    for _ in range(100):
        if any(isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent):
            break
        await asyncio.sleep(0)

    await transport.frames.put(input_epoch("input-device-2"))
    for _ in range(100):
        if sum(
            isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent
        ) == 2:
            break
        await asyncio.sleep(0)
    assert [
        frame.to_phase
        for frame in transport.sent
        if isinstance(frame, VoiceSessionPhaseChangedFrame)
    ] == ["starting", "active"]
    assert not any(
        isinstance(frame, ConfirmationRequestedFrame) for frame in transport.sent
    )

    await endpoint.detached()
    transport.client_hello = SessionHelloFrame(
        supported_protocol_versions=(2,),
        protocol_version=2,
        last_session_sequence=4,
        last_journal_sequence=0,
    )
    assert active_conversations.resolve(context) is None
    await transport.frames.put(
        ConfirmationDecisionFrame(
            confirmation_id="confirmation-1",
            action_digest=digest,
            approved=False,
        )
    )
    for _ in range(100):
        if any(
            isinstance(frame, ConfirmationResolutionFrame)
            for frame in transport.sent
        ):
            break
        await asyncio.sleep(0)
    blocked = next(
        frame
        for frame in transport.sent
        if isinstance(frame, ConfirmationResolutionFrame)
    )
    assert blocked.error == "confirmation_restatement_required"
    assert accepted_decisions == []

    await transport.frames.put(input_epoch("input-2"))
    for _ in range(100):
        if any(
            isinstance(frame, ConfirmationRequestedFrame)
            for frame in transport.sent
        ):
            break
        await asyncio.sleep(0)

    restated = next(
        frame
        for frame in transport.sent
        if isinstance(frame, ConfirmationRequestedFrame)
    )
    assert restated.confirmation_id == "confirmation-1"
    assert restated.action_digest == digest
    assert restated.summary == "删除文件 A（不可撤销）"
    assert restated.required_channel == "strong"
    for _ in range(100):
        if active_conversations.resolve(context) is not None:
            break
        await asyncio.sleep(0)
    assert active_conversations.resolve(context) is not None
    assert work_registry.rebuilt == [identity]
    event_tail = next(
        frame for frame in transport.sent if isinstance(frame, VoiceSessionEventTailFrame)
    )
    assert event_tail.resume_from_sequence == 4
    assert event_tail.through_sequence == 6
    assert [event.session_sequence for event in event_tail.events] == [5]

    await endpoint.detached()
    await transport.frames.put(input_epoch("input-3"))
    for _ in range(100):
        if sum(
            isinstance(frame, ConfirmationRequestedFrame)
            for frame in transport.sent
        ) == 2:
            break
        await asyncio.sleep(0)
    assert sum(
        isinstance(frame, ConfirmationRequestedFrame) for frame in transport.sent
    ) == 2
    assert work_registry.rebuilt == [identity, identity]

    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)


async def test_quiesced_endpoint_reopens_conversation_without_ending_session() -> None:
    transport = QueuedEpochTransport()
    runtime_factory = ReopeningRuntimeFactory()
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-quiesce",
        thread_id="thread-quiesce",
    )
    endpoint = VoiceSessionWebSocketSession(
        identity=identity,
        context=InteractionContext(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            device_id=identity.device_id,
            voice_session_id=identity.voice_session_id,
            thread_id=identity.thread_id,
            turn_id="turn-1",
            generation=1,
        ),
        profile="cascaded-default",
        runtime_factory=runtime_factory,
        journal=InMemoryConversationJournal(),
        transport=transport,
        admission=LocalVoiceSessionAdmissionController(),
        fast_resume_window_s=0.001,
        event_tail_capacity=2,
    )
    run_task = asyncio.create_task(endpoint.run())
    await transport.frames.put(input_epoch("input-1"))
    for _ in range(100):
        if any(isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent):
            break
        await asyncio.sleep(0)

    await endpoint.detached()
    transport.client_hello = SessionHelloFrame(
        supported_protocol_versions=(2,),
        protocol_version=2,
        last_session_sequence=0,
        last_journal_sequence=0,
    )
    for _ in range(100):
        runtime = endpoint._runtime
        if runtime is not None and runtime.is_quiesced:
            break
        await asyncio.sleep(0.001)

    assert runtime_factory.conversations[0].closed is True
    assert run_task.done() is False

    await transport.frames.put(input_epoch("input-2"))
    for _ in range(100):
        if sum(
            isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent
        ) == 2:
            break
        await asyncio.sleep(0.001)

    assert len(runtime_factory.conversations) == 2
    snapshot = next(
        frame for frame in transport.sent if isinstance(frame, VoiceSessionSnapshotFrame)
    )
    assert snapshot.phase == "reconnecting"
    assert snapshot.session_sequence == 5
    assert endpoint._runtime is not None
    assert endpoint._runtime.phase.value == "active"
    assert run_task.done() is False

    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)


async def test_input_budget_failure_closes_actual_engine_and_coordinator() -> None:
    from server.realtime.capabilities.asr import AsrEndpointHint, AsrTranscriptDelta
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.capabilities.turn_manager import ObserveAsrEvent
    from server.realtime.runtime import RealtimeRuntimeFactory
    from server.turn_policy.policy import TurnPolicy
    from server.turn_policy.semantic_input import SemanticInputBudget
    from tests.realtime.test_cascaded_engine import context, engine

    class RecordingCoordinator(CoordinatedTurnManagerCapabilityAdapter):
        async def open(self, *, context):
            self.session = await super().open(context=context)
            return self.session

    from server.realtime import AppendItem, RequestResponse
    from server.realtime.capabilities import (
        LegacyBrainCapabilityAdapter,
        LegacyTtsCapabilityAdapter,
    )
    from server.speech.tts import SynthesizedAudioChunk
    from server.turn_policy.semantic_interruption import (
        InterruptionClassification,
        InterruptionLabel,
    )

    brain_started, brain_cancelled = asyncio.Event(), asyncio.Event()
    tts_started, tts_cancelled = asyncio.Event(), asyncio.Event()
    classifier_started, classifier_cancelled = asyncio.Event(), asyncio.Event()

    class ActiveBrain:
        async def stream(self, turn):
            try:
                brain_started.set()
                yield "已经开始回答。"
                await asyncio.Event().wait()
            finally:
                brain_cancelled.set()

    class ActiveTts:
        async def synthesize_duplex(self, text_stream):
            try:
                async for text in text_stream:
                    tts_started.set()
                    yield SynthesizedAudioChunk(pcm16=b"\x00\x00" * 160, sample_rate_hz=16000, is_final=False)
                    await asyncio.Event().wait()
            finally:
                tts_cancelled.set()

    class ActiveClassifier:
        async def classify_request(self, request):
            try:
                classifier_started.set()
                await asyncio.Event().wait()
                return InterruptionClassification(InterruptionLabel.INTERRUPT, 1)
            finally:
                classifier_cancelled.set()

    journal = InMemoryConversationJournal()
    coordinator = RecordingCoordinator(TurnPolicy, input_evidence_journal=journal,
                                       input_budget=SemanticInputBudget(max_text_bytes=6), semantic_interruption_classifier=ActiveClassifier())
    cascaded = engine()
    cascaded._turn_manager = coordinator
    cascaded._brain = LegacyBrainCapabilityAdapter(ActiveBrain())
    cascaded._tts = LegacyTtsCapabilityAdapter(ActiveTts())
    active = ActiveRealtimeConversations()
    factory = RealtimeRuntimeFactory(engine=cascaded, journal=journal, active_conversations=active)
    ctx = context()
    transport = EpochTransport()
    endpoint = VoiceSessionWebSocketSession(
        identity=VoiceSessionIdentity(tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                     device_id=ctx.device_id, voice_session_id=ctx.voice_session_id, thread_id=ctx.thread_id),
        context=ctx, profile=None, runtime_factory=factory, journal=journal,
        transport=transport, admission=LocalVoiceSessionAdmissionController(),
    )
    running = asyncio.create_task(endpoint.run())
    try:
        async with asyncio.timeout(1):
            while not any(isinstance(frame, VoiceSessionReadyFrame) for frame in transport.sent):
                await asyncio.sleep(0)
        await endpoint._conversation.send(AppendItem(
            command_id="seed", idempotency_key="seed", context=ctx,
            draft=ConversationItemDraft(item_id="user-seed", context=ctx, kind=ConversationItemKind.USER_INPUT,
                                       status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent("seed"),))))
        await endpoint._conversation.send(RequestResponse(command_id="start-response", idempotency_key="start-response",
                                                          context=ctx, response_id="active-response", minimum_thread_sequence=1))
        async with asyncio.timeout(1):
            await brain_started.wait()
            await tts_started.wait()
        await coordinator.session.send(ObserveAsrEvent(event=AsrEndpointHint(context=ctx, revision=1, text="北京")))
        async with asyncio.timeout(1):
            await classifier_started.wait()
        assert not classifier_cancelled.is_set()
        assert coordinator.session._classifier_executor.pending_count > 0
        assert not brain_cancelled.is_set() and not tts_cancelled.is_set()
        await coordinator.session.send(ObserveAsrEvent(event=AsrTranscriptDelta(
            context=ctx, revision=2, delta="北京上海", accumulated_text="北京上海", audio_timestamp_us=0)))
        async with asyncio.timeout(2):
            await running
        failures = [frame for frame in transport.sent if isinstance(frame, VoiceSessionFailureFrame)]
        assert len(failures) == 1
        assert failures[0].code == "semantic_input_rejected"
        assert failures[0].session_disposition == "close"
        assert "未确认保存" in failures[0].safe_message
        assert transport._closed.is_set()
        assert coordinator.session._closed
        assert coordinator.session._actor.done()
        assert coordinator.session._input is None
        assert coordinator.session._evidence._worker.done()
        assert not coordinator.session._all_jobs
        assert brain_cancelled.is_set() and tts_cancelled.is_set() and classifier_cancelled.is_set()
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
