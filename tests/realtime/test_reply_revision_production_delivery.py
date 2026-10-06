"""Exercise real decorator queues and the final WebSocket frame boundary."""

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    SpokenContent,
    TextContent,
)
from server.realtime import (
    AppendItem,
    AppendSpeechText,
    AssistantYieldRequested,
    AudioDelta,
    CancelResponse,
    CancelSpeech,
    DeliverItem,
    DeliveryMode,
    DisplayContentDelta,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    SpeechAudioDelta,
    SpeechStarted,
    StartSpeech,
)
from server.realtime.capabilities import (
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyVadCapabilityAdapter,
)
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.cascaded import CascadedRealtimeEngine
from server.realtime.registry import ActiveRealtimeConversations
from server.realtime.runtime import RealtimeRuntimeFactory
from server.realtime.speech.delivery import SpeechDeliveryStatus
from server.realtime.transport.websocket import RealtimeWebSocketFrameBridge
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.transport.frames import AssistantAudioChunkFrame, AssistantSpeechCancelledFrame
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_cascaded_engine import (
    EchoDuplexTts,
    GatedDuplexTts,
    GatedStreamingBrain,
    context,
)


class Transport:
    def __init__(self):
        self.frames = []

    async def send(self, frame):
        self.frames.append(frame)


async def open_core(*, brain=None, tts=None):
    return await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig())),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain or GatedStreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(tts or EchoDuplexTts()),
    ).open(context=context(), profile=None)


async def append_user(conversation, *, spoken=None):
    await conversation.send(AppendItem(command_id="user", idempotency_key="user", context=context(),
        draft=ConversationItemDraft(item_id="user", context=context(),
            kind=ConversationItemKind.USER_INPUT, status=ConversationItemStatus.COMPLETED,
            producer="test", content=(TextContent("查天气"),),
            spoken=SpokenContent(spoken) if spoken else None)))


async def request(conversation):
    await conversation.send(RequestResponse(command_id="request", idempotency_key="request",
        context=context(), response_id="a", minimum_thread_sequence=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("wrappers", ["none", "tools", "tools_and_agents"])
async def test_managed_production_queue_and_bridge_recheck_same_permission(wrappers):
    core = await open_core()

    class FixedEngine:
        async def open(self, **kwargs):
            return core

    factory = RealtimeRuntimeFactory(
        engine=FixedEngine(), journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
        tool_control_handler_factory=(lambda: object()) if wrappers != "none" else None,
        agent_task_supervisor=object() if wrappers == "tools_and_agents" else None,
        delegation_request_factory=(lambda event: None) if wrappers == "tools_and_agents" else None,
    )
    managed = await factory.open(context=context(), profile=None)
    transport = Transport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=managed, transport=transport)
    try:
        await append_user(managed)
        await request(managed)
        async with asyncio.timeout(.5):
            while not any(isinstance(entry[1], AudioDelta) for entry in managed._events._queue):
                await asyncio.sleep(.001)
        old_audio = next(entry[1] for entry in managed._events._queue if isinstance(entry[1], AudioDelta))
        await managed.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
            context=context(), response_id="a", reason="user_cancelled"))
        # Also simulate an event fetched by the endpoint immediately before revocation.
        await bridge.handle_event(old_audio)
        delivered = []
        async with asyncio.timeout(.5):
            async for event in managed.events():
                delivered.append(event)
                await bridge.handle_event(event)
                if isinstance(event, ResponseCancelled):
                    break
        assert not any(isinstance(event, (AudioDelta, DisplayContentDelta)) for event in delivered)
        assert not any(isinstance(frame, AssistantAudioChunkFrame) for frame in transport.frames)
        assert not managed.output_delivery_allowed(old_audio)
    finally:
        await managed.close()


@pytest.mark.asyncio
async def test_cancel_during_natural_completion_emits_playback_stop_without_second_terminal(monkeypatch):
    from server.realtime.journaled import JournaledRealtimeConversation
    brain = GatedStreamingBrain()
    core = await open_core(brain=brain)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                engine_conversation=core)
    transport = Transport()
    bridge = RealtimeWebSocketFrameBridge(context=context(), conversation=conversation, transport=transport)
    entered, release = asyncio.Event(), asyncio.Event()
    original = core._input_pipeline.invalidate_response

    async def paused(response_id, **kwargs):
        entered.set()
        await release.wait()
        await original(response_id, **kwargs)

    monkeypatch.setattr(core._input_pipeline, "invalidate_response", paused)
    stream = core.events()
    cancel = None
    try:
        await append_user(conversation)
        await request(conversation)
        async with asyncio.timeout(.5):
            async for event in stream:
                await bridge.handle_event(event)
                if isinstance(event, AudioDelta):
                    break
        assert any(isinstance(frame, AssistantAudioChunkFrame) for frame in transport.frames)
        cancel = asyncio.create_task(conversation.send(CancelResponse(
            command_id="cancel", idempotency_key="cancel",
            context=replace(context(), turn_id="new-input", generation=context().generation + 1), response_id="a",
            reason="user_cancelled")))
        await asyncio.wait_for(entered.wait(), .5)
        brain.release.set()
        async with asyncio.timeout(.5):
            while core._active_response_id is not None:
                await asyncio.sleep(.001)
        release.set()
        await asyncio.wait_for(cancel, .5)
        events = []
        async with asyncio.timeout(.5):
            async for event in stream:
                events.append(event)
                await bridge.handle_event(event)
                if isinstance(event, AssistantYieldRequested):
                    break
        assert sum(isinstance(event, ResponseCompleted) for event in events) == 1
        assert not any(isinstance(event, ResponseCancelled) for event in events)
        stop_event = next(event for event in events if isinstance(event, AssistantYieldRequested))
        assert stop_event.context.turn_id == context().turn_id
        assert stop_event.context.generation == context().generation
        stops = [frame for frame in transport.frames if isinstance(frame, AssistantSpeechCancelledFrame)]
        assert len(stops) == 1
        assert stops[0].generation == context().generation
    finally:
        release.set()
        if cancel is not None:
            await asyncio.gather(cancel, return_exceptions=True)
        await conversation.close()


@pytest.mark.asyncio
async def test_failed_preparing_never_starts_brain_and_cleans_admission(monkeypatch):
    from server.realtime.journaled import JournaledRealtimeConversation
    brain = GatedStreamingBrain()
    calls = []
    original_stream = brain.stream

    async def record(turn):
        calls.append(turn)
        async for value in original_stream(turn):
            yield value

    monkeypatch.setattr(brain, "stream", record)
    core = await open_core(brain=brain)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                engine_conversation=core)

    async def fail(*args, **kwargs):
        raise RuntimeError("preparing failed")

    monkeypatch.setattr(core._input_pipeline, "response_started", fail)
    try:
        await append_user(conversation)
        with pytest.raises(RuntimeError, match="preparing failed"):
            await request(conversation)
        await asyncio.sleep(.01)
        assert calls == []
        assert core._response_task is None
        assert core._active_response_id is None
        assert core._response_admitted_by_id == {}
    finally:
        await conversation.close()


@pytest.mark.asyncio
async def test_direct_speech_cancellation_revokes_queued_audio():
    from server.realtime.journaled import JournaledRealtimeConversation
    core = await open_core(tts=GatedDuplexTts())
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                engine_conversation=core)
    try:
        await append_user(conversation, spoken="直接播报")
        await conversation.send(DeliverItem(command_id="deliver", idempotency_key="deliver",
            context=context(), delivery_id="direct", item_id="user", mode=DeliveryMode.SPEECH))
        async with asyncio.timeout(.5):
            while not any(isinstance(event, AudioDelta) for event in core._events._queue):
                await asyncio.sleep(.001)
        await conversation.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
            context=context(), response_id="delivery:direct", reason="user_cancelled"))
        delivered = []
        async with asyncio.timeout(.5):
            async for event in core.events():
                delivered.append(event)
                if isinstance(event, ResponseCancelled):
                    break
        assert not any(isinstance(event, AudioDelta) for event in delivered)
    finally:
        await conversation.close()


@pytest.mark.asyncio
async def test_direct_speech_natural_completion_race_settles_delivery_before_stop(monkeypatch):
    from server.realtime.journaled import JournaledRealtimeConversation
    tts = GatedDuplexTts()
    core = await open_core(tts=tts)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                engine_conversation=core)
    entered, release = asyncio.Event(), asyncio.Event()
    original = core._input_pipeline.invalidate_response

    async def paused(response_id, **kwargs):
        entered.set()
        await release.wait()
        await original(response_id, **kwargs)

    monkeypatch.setattr(core._input_pipeline, "invalidate_response", paused)
    cancel = None
    try:
        await append_user(conversation, spoken="直接播报")
        await conversation.send(DeliverItem(command_id="deliver", idempotency_key="deliver",
            context=context(), delivery_id="direct", item_id="user", mode=DeliveryMode.SPEECH))
        async with asyncio.timeout(.5):
            while not any(isinstance(event, AudioDelta) for event in core._events._queue):
                await asyncio.sleep(.001)
        cancel = asyncio.create_task(conversation.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
            context=replace(context(), turn_id="new-input", generation=context().generation + 1),
            response_id="delivery:direct", reason="user_cancelled")))
        await asyncio.wait_for(entered.wait(), .5)
        tts.release.set()
        async with asyncio.timeout(.5):
            while core._response_task is not None:
                await asyncio.sleep(.001)
        release.set()
        await asyncio.wait_for(cancel, .5)
        speech_id = "response:delivery:direct"
        record = await core._speech_deliveries.get(speech_id)
        assert record is not None
        assert record.status is SpeechDeliveryStatus.INTERRUPTED
        assert record.reason == "user_cancelled"
        assert speech_id not in core._unsettled_model_speech_ids
        events = list(core._events._queue)
        assert sum(isinstance(event, ResponseCompleted) for event in events) == 1
        assert not any(isinstance(event, ResponseCancelled) for event in events)
        stops = [event for event in events if isinstance(event, AssistantYieldRequested)]
        assert len(stops) == 1
        assert stops[0].context.generation == context().generation
        assert stops[0].context.turn_id == context().turn_id
    finally:
        release.set()
        tts.release.set()
        if cancel is not None:
            await asyncio.gather(cancel, return_exceptions=True)
        await conversation.close()


@pytest.mark.asyncio
async def test_external_speech_uses_speech_identity_even_with_source_response_context():
    core = await open_core(tts=GatedDuplexTts())
    ctx = replace(context(), response_id="source-reply")
    try:
        await core.send(StartSpeech(command_id="start", idempotency_key="start", context=ctx,
            speech_id="external"))
        await core.send(AppendSpeechText(command_id="text", idempotency_key="text", context=ctx,
            speech_id="external", text_sequence=1, delta="播放内容"))
        async with asyncio.timeout(.5):
            while not any(isinstance(event, SpeechAudioDelta) for event in core._events._queue):
                await asyncio.sleep(.001)
        assert any(isinstance(event, SpeechStarted) for event in core._events._queue)
        audio = next(event for event in core._events._queue if isinstance(event, SpeechAudioDelta))
        assert core.output_delivery_allowed(audio)
        await core.send(CancelSpeech(command_id="cancel", idempotency_key="cancel", context=ctx,
            speech_id="external", reason="cancelled"))
        assert not core.output_delivery_allowed(audio)
    finally:
        await core.close()
