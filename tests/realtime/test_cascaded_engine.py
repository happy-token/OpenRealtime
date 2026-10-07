from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    DisplayContent,
    InMemoryConversationJournal,
    JournalScope,
    SpokenContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.realtime import (
    AgentDelegationRequestProposed,
    AppendAudio,
    AppendItem,
    AppendSpeechText,
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CancelResponse,
    CancelSpeech,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    DialogueStateChanged,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InputTranscriptDelta,
    InterruptedContextPolicy,
    ItemDeliveryCancelled,
    ItemDeliveryCompleted,
    ItemDeliveryFailed,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemDisplayPresented,
    ItemProjected,
    JournaledRealtimeConversation,
    PlaybackPrecision,
    RealtimeCapabilityFailed,
    RealtimeTurnController,
    ReportPlaybackProgress,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechAudioCompleted,
    SpeechAudioDelta,
    SpeechCancelled,
    SpeechContextPolicy,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextCommitted,
    SpokenContentDelta,
    StartSpeech,
    ToolRequested,
)
from server.realtime.capabilities import (
    BrainResponseStarted,
    BrainTextDelta,
    CancelBrainResponse,
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyTurnManagerCapabilityAdapter,
    LegacyVadCapabilityAdapter,
    RequestBrainResponse,
)
from server.realtime.capabilities.brain_streaming import (
    BrainDelegationCall,
    BrainToolCall,
)
from server.realtime.cascaded import CascadedRealtimeEngine
from server.realtime.plugins import CapabilityContext
from server.realtime.profile import (
    AudioFormat,
    DataGrant,
    EngineKind,
    FailurePolicy,
    PluginKind,
    PluginManifest,
    PluginPlacement,
    PluginRegistry,
    PluginSelection,
    ProfileResolver,
    RealtimeProfile,
)
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
    SpeechDeliveryStatus,
)
from server.realtime.tool_controller import RealtimeToolController
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.speech.tts import SynthesizedAudioChunk
from server.tools.canonical import LatencyClass
from server.tools.control import DefaultToolControlHandler
from server.tools.fast_loop import FastToolLoop
from server.tools.policy_gateway import (
    DefaultToolPolicyGateway,
    ToolExecutor,
    ToolPolicyContext,
)
from server.turn_policy.dual_intent import DualIntent
from server.turn_policy.policy import TurnPolicy
from tests.tools.test_policy_gateway import registry


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


def pcm_frame(*, sequence: int, amplitude: int) -> AudioFrame:
    samples = array.array("h", [amplitude] * 512)
    return AudioFrame(
        stream_id="input-1",
        sequence=sequence,
        timestamp_us=sequence * 32_000,
        duration_us=32_000,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate_hz=16_000,
        channels=1,
        data=samples.tobytes(),
    )


class SilentBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        if False:
            yield ""


class RecordingContextBrain:
    def __init__(self) -> None:
        self.turns: list[TurnContent] = []

    async def stream(self, turn) -> AsyncIterator[str]:
        self.turns.append(turn)
        yield "收到。"


class SilentTts:
    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        del text
        if False:
            yield SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=24_000, is_final=True)


class StreamingBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        assert turn.text == "你好，帮我查天气"
        yield "你好，"
        yield "今天会下雨。"


class EchoDuplexTts:
    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for text in text_stream:
            yield SynthesizedAudioChunk(
                pcm16=text.encode(),
                sample_rate_hz=24_000,
                is_final=False,
            )


class TimeoutOnIdleTts:
    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        iterator = text_stream.__aiter__()
        while True:
            try:
                text = await asyncio.wait_for(anext(iterator), timeout=0.05)
            except StopAsyncIteration:
                return
            yield SynthesizedAudioChunk(
                pcm16=text.encode(), sample_rate_hz=24_000, is_final=False
            )


class FailingDuplexTts:
    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for _text in text_stream:
            raise RuntimeError("TTS websocket disconnected")
        if False:
            yield SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=24_000, is_final=True)


class GatedDuplexTts:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for text in text_stream:
            yield SynthesizedAudioChunk(
                pcm16=text.encode(), sample_rate_hz=24_000, is_final=False
            )
            await self.release.wait()


class SlowCancellationDuplexTts:
    """External TTS double whose provider cleanup outlives floor arbitration."""

    def __init__(self) -> None:
        self.cleanup_release = asyncio.Event()

    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        try:
            async for text in text_stream:
                yield SynthesizedAudioChunk(
                    pcm16=text.encode(), sample_rate_hz=24_000, is_final=False
                )
                await asyncio.Event().wait()
        finally:
            await self.cleanup_release.wait()


class SlowCancellationBrain:
    """Brain double whose provider cleanup ignores task cancellation."""

    def __init__(self) -> None:
        self.cleanup_release = asyncio.Event()

    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        try:
            yield "已经开始回复"
            await asyncio.Event().wait()
        finally:
            await self.cleanup_release.wait()


class CancellationPropagatingBrainProvider:
    async def open(self, *, context: InteractionContext):
        return CancellationPropagatingBrainSession(context)


class CancellationPropagatingBrainSession:
    def __init__(self, session_context: InteractionContext) -> None:
        self._context = session_context
        self._events: asyncio.Queue[object] = asyncio.Queue()

    async def send(self, command) -> None:
        if isinstance(command, CancelBrainResponse):
            raise asyncio.CancelledError
        assert isinstance(command, RequestBrainResponse)
        response_context = replace(
            command.context or self._context,
            response_id=command.response_id,
        )
        await self._events.put(
            BrainResponseStarted(
                context=response_context,
                response_id=command.response_id,
                response_sequence=1,
                request_token=command.request_token,
            )
        )
        await self._events.put(
            BrainTextDelta(
                context=response_context,
                response_id=command.response_id,
                response_sequence=2,
                delta="正在回复",
                request_token=command.request_token,
            )
        )

    async def events(self):
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        await self._events.put(None)


class GatedStreamingBrain:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        yield "第一段"
        await self.release.wait()
        yield "第二段"


class EmptyThenTextBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        self.calls += 1
        if self.calls == 1:
            return
        yield "第二轮可以正常回复"


class AgentResultBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        assert turn.text == "后台任务已完成"
        yield "任务结果已经准备好了。"


class DelegatingBrain:
    async def stream(self, turn):
        assert turn.text == "后台检查项目"
        yield BrainDelegationCall(
            delegation_request_id="delegation-1",
            instruction="Inspect the project without modifying files",
            agent_name="codex",
        )


class PausingToolBrain:
    async def stream_with_tools(self, turn, *, tool_results):
        assert turn.text == "现在几点"
        yield BrainToolCall(
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1",
            arguments={"timezone": "Asia/Shanghai"},
            latency=LatencyClass.FAST,
        )
        feedback = await tool_results.wait("call-1")
        yield f"现在是{feedback.model_output}。"


class PausingVariableToolBrain:
    async def stream_with_tools(self, turn, *, tool_results):
        assert turn.text == "今天天气怎么样"
        yield BrainToolCall(
            call_id="call-1",
            tool_name="weather",
            tool_version="1.0.0",
            arguments={"city": "Shanghai"},
            latency=LatencyClass.VARIABLE,
        )
        yield "我查一下，马上告诉你。"
        feedback = await tool_results.wait("call-1")
        yield f"今天天气{feedback.model_output}。"


class FailingBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        raise RuntimeError("model service timed out")
        yield ""


class HangingBrain:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        if False:
            yield ""


class GainProcessorBinding:
    async def open(self, *, context: CapabilityContext, config: dict[str, object]):
        del context
        return GainProcessorSession(int(config["gain"]))


class GainProcessorSession:
    def __init__(self, gain: int) -> None:
        self._gain = gain

    async def process(self, audio: AudioFrame) -> AudioFrame:
        samples = array.array("h")
        samples.frombytes(audio.data)
        amplified = array.array("h", (sample * self._gain for sample in samples))
        return AudioFrame(
            stream_id=audio.stream_id,
            sequence=audio.sequence,
            timestamp_us=audio.timestamp_us,
            duration_us=audio.duration_us,
            encoding=audio.encoding,
            sample_rate_hz=audio.sample_rate_hz,
            channels=audio.channels,
            data=amplified.tobytes(),
        )

    async def close(self) -> None:
        return None


class ConfigurableVadBinding:
    def __init__(self) -> None:
        self.received_config: dict[str, object] | None = None

    async def open(
        self,
        *,
        context: InteractionContext,
        config: dict[str, object],
    ):
        self.received_config = config
        adapter = LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(
                    energy_threshold=int(config["threshold"]),
                    silence_duration_ms=32,
                )
            )
        )
        return await adapter.open(context=context)


class FloorClaimClassifier:
    async def classify(self, *, generation: int, overlap_ms: float, text: str):
        del generation, overlap_ms, text
        return DualIntent.FLOOR_CLAIM


class TrackedSession:
    def __init__(self) -> None:
        self.closed = False

    async def send(self, command) -> None:
        del command

    async def events(self):
        while not self.closed:
            await asyncio.sleep(1)
        if False:
            yield

    async def close(self) -> None:
        self.closed = True


class TrackedProvider:
    def __init__(self) -> None:
        self.session = TrackedSession()

    async def open(self, *, context: InteractionContext):
        del context
        return self.session


class FailingOpenProvider:
    async def open(self, *, context: InteractionContext):
        del context
        raise RuntimeError("TTS connection failed")


class ProviderTimeoutBrainSession(TrackedSession):
    async def send(self, command) -> None:
        if isinstance(command, RequestBrainResponse):
            raise TimeoutError("model provider timed out")


class ProviderTimeoutBrainProvider:
    async def open(self, *, context: InteractionContext):
        del context
        return ProviderTimeoutBrainSession()


class DisconnectingVadSession(TrackedSession):
    async def events(self):
        await asyncio.sleep(0)
        raise RuntimeError("VAD provider disconnected")
        if False:
            yield


class DisconnectingVadProvider:
    def __init__(self) -> None:
        self.session = DisconnectingVadSession()

    async def open(self, *, context: InteractionContext):
        del context
        return self.session


def engine() -> CascadedRealtimeEngine:
    return CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("你好，帮我查天气")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
    )


async def test_partial_engine_open_closes_every_successful_capability() -> None:
    vad = TrackedProvider()
    asr = TrackedProvider()
    turn_manager = TrackedProvider()
    brain = TrackedProvider()

    with pytest.raises(RuntimeError, match="TTS connection failed"):
        await CascadedRealtimeEngine(
            vad=vad,
            asr=asr,
            turn_manager=turn_manager,
            brain=brain,
            speech_renderer=DeterministicSpeechRenderer(),
            tts=FailingOpenProvider(),
        ).open(context=context(), profile=None)

    assert vad.session.closed is True
    assert asr.session.closed is True
    assert turn_manager.session.closed is True
    assert brain.session.closed is True


async def test_input_capability_disconnect_is_a_public_realtime_event() -> None:
    conversation = await CascadedRealtimeEngine(
        vad=DisconnectingVadProvider(),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
    ).open(context=context(), profile=None)

    failed = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(failed, RealtimeCapabilityFailed)
    assert failed.capability == "vad"
    assert failed.error == "VAD provider disconnected"
    await conversation.close()


async def test_append_audio_reaches_one_committed_public_user_transcript() -> None:
    conversation = await engine().open(context=context(), profile=None)
    events = conversation.events()
    second_turn = replace(context(), turn_id="turn-2", generation=2)

    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=second_turn,
            frame=pcm_frame(sequence=0, amplitude=1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="audio-2",
            idempotency_key="audio-2",
            context=second_turn,
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )

    emitted = []
    while not any(
        isinstance(event, InputTranscriptCompleted) for event in emitted
    ):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    completed = next(
        event for event in emitted if isinstance(event, InputTranscriptCompleted)
    )
    assert completed.text == "你好，帮我查天气"
    assert completed.transcript_revision == 1
    assert completed.context.turn_id == "turn-2"
    assert completed.context.generation == 2

    await conversation.close()


async def test_asr_partial_is_exposed_before_the_user_turn_is_committed() -> None:
    conversation = await engine().open(context=context(), profile=None)
    events = conversation.events()
    second_turn = replace(context(), turn_id="turn-2", generation=2)

    await conversation.send(
        AppendAudio(
            command_id="audio-partial",
            idempotency_key="audio-partial",
            context=second_turn,
            frame=pcm_frame(sequence=0, amplitude=1_000),
        )
    )

    emitted = [await asyncio.wait_for(anext(events), timeout=0.2) for _ in range(2)]
    partial = next(event for event in emitted if isinstance(event, InputTranscriptDelta))
    assert partial.text == "你好，帮我查天气"
    assert partial.delta == "你好，帮我查天气"
    assert partial.transcript_revision == 1
    assert partial.context.turn_id == "turn-2"
    assert partial.context.generation == 2

    await conversation.close()


async def test_projected_user_turn_streams_brain_text_into_tts_and_public_audio() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(StreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user-1",
            idempotency_key="append-user-1",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="realtime-control-plane",
                content=(TextContent("你好，帮我查天气"),),
            ),
        )
    )
    assert isinstance(await anext(events), ItemProjected)

    await conversation.send(
        RequestResponse(
            command_id="response-1",
            idempotency_key="response-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )

    emitted = []
    for _ in range(20):
        event = await anext(events)
        emitted.append(event)
        if isinstance(event, ResponseCompleted):
            break
    assert isinstance(emitted[0], ResponseStarted)
    assert "".join(
        event.delta for event in emitted if isinstance(event, SpokenContentDelta)
    ) == "你好，今天会下雨。"
    assert b"".join(event.frame.data for event in emitted if isinstance(event, AudioDelta)) == (
        "你好，今天会下雨。".encode()
    )
    assert isinstance(emitted[-1], ResponseCompleted)

    await conversation.close()


async def test_turn_stays_speaking_until_the_client_finishes_playback() -> None:
    brain = GatedStreamingBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-playback-user",
            idempotency_key="append-playback-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="playback-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试播放状态"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="playback-response",
            idempotency_key="playback-response",
            context=context(),
            response_id="playback-response",
            minimum_thread_sequence=1,
            output_item_id="playback-assistant",
        )
    )

    before_start = []
    while not any(isinstance(event, AudioDelta) for event in before_start):
        before_start.append(await asyncio.wait_for(anext(events), timeout=0.2))
    speech_id = next(
        event.speech_id for event in before_start if isinstance(event, AudioDelta)
    )
    brain.release.set()
    after_start = []
    while not any(isinstance(event, ResponseCompleted) for event in after_start):
        after_start.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert not any(
        isinstance(event, DialogueStateChanged) and event.to_state.value == "idle"
        for event in after_start
    )

    await conversation.send(
        ReportPlaybackProgress(
            command_id="playback-started",
            idempotency_key="playback-started",
            context=context(),
            speech_id=speech_id,
            delivered_text_end=0,
            played_audio_end_us=0,
            completed=False,
        )
    )
    playback_started = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(playback_started, SpeechPlaybackProgress):
        playback_started = await asyncio.wait_for(anext(events), timeout=0.2)

    spoken = "第一段第二段"
    await asyncio.sleep(0.02)
    await conversation.send(
        ReportPlaybackProgress(
            command_id="playback-finished",
            idempotency_key="playback-finished",
            context=context(),
            speech_id=speech_id,
            delivered_text_end=len(spoken),
            played_audio_end_us=1,
            completed=True,
        )
    )
    terminal = [
        await asyncio.wait_for(anext(events), timeout=0.2),
        await asyncio.wait_for(anext(events), timeout=0.2),
    ]
    assert isinstance(terminal[0], SpeechPlaybackProgress)
    assert any(
        isinstance(event, DialogueStateChanged) and event.to_state.value == "idle"
        for event in terminal
    )
    await conversation.close()


async def test_barge_in_stops_playback_even_after_response_generation_completed() -> None:
    """Response generation and client playback have independent lifecycles."""

    deliveries = InMemorySpeechDeliveryStore()
    brain = GatedStreamingBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("北京的")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=FloorClaimClassifier(),
        ),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-before-playback-barge-in",
            idempotency_key="append-before-playback-barge-in",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-before-playback-barge-in",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("请问我想查天气"),),
            ),
        )
    )
    await anext(events)
    response_id = "completed-before-playback-barge-in"
    await conversation.send(
        RequestResponse(
            command_id=response_id,
            idempotency_key=response_id,
            context=replace(context(), response_id=response_id),
            response_id=response_id,
            minimum_thread_sequence=1,
            output_item_id="assistant-before-playback-barge-in",
        )
    )

    speech_id = ""
    emitted = []
    while not speech_id:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, AudioDelta):
            speech_id = event.speech_id or ""
    # Release the second Brain chunk and wait until generation is terminal,
    # while playback deliberately remains active.
    brain.release.set()
    while not any(isinstance(event, ResponseCompleted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))

    interrupt_context = replace(context(), turn_id="turn-2", generation=2)
    await conversation.send(
        AppendAudio(
            command_id="barge-in-loud",
            idempotency_key="barge-in-loud",
            context=interrupt_context,
            frame=pcm_frame(sequence=10, amplitude=1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="barge-in-silence",
            idempotency_key="barge-in-silence",
            context=interrupt_context,
            frame=pcm_frame(sequence=11, amplitude=0),
        )
    )

    after_barge_in = []
    while not any(isinstance(event, InputTranscriptCompleted) for event in after_barge_in):
        after_barge_in.append(await asyncio.wait_for(anext(events), timeout=0.5))
    assert any(isinstance(event, AssistantYieldRequested) for event in after_barge_in)
    completed_terminals = [
        event for event in (*emitted, *after_barge_in) if isinstance(event, ResponseCompleted)
    ]
    assert len(completed_terminals) == 1
    record = await deliveries.get(speech_id)
    assert record is not None
    assert record.status is SpeechDeliveryStatus.INTERRUPTED

    # The stop acknowledgement can arrive after the server requested the
    # interruption; it must refine, not reopen, the terminal delivery record.
    await conversation.send(
        ReportPlaybackProgress(
            command_id="late-stop-playhead",
            idempotency_key="late-stop-playhead",
            context=interrupt_context,
            speech_id=speech_id,
            delivered_text_end=len("第一段"),
            played_audio_end_us=320_000,
            precision=PlaybackPrecision.EXACT,
            completed=False,
        )
    )
    progress = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(progress, SpeechPlaybackProgress):
        progress = await asyncio.wait_for(anext(events), timeout=0.2)
    record = await deliveries.get(speech_id)
    assert record is not None
    assert record.status is SpeechDeliveryStatus.INTERRUPTED
    assert record.delivered_speech_transcript == "第一段"
    await conversation.close()


@pytest.mark.parametrize("cache_mode", ["bare", "speech_direct", "speech_prepared"])
async def test_failed_empty_response_releases_tts_before_the_next_turn(cache_mode) -> None:
    from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline

    class EmptyFirstTurnBrain:
        async def stream(self, turn):
            if turn.text == "第1轮":
                return
            yield "第二轮可以正常回复"

    provider = EmptyFirstTurnBrain()
    tts = EchoDuplexTts()
    brain = (provider if cache_mode == "bare" else
             SpeculativeSpeechPipeline(brain=provider, tts=tts))
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(tts if cache_mode == "bare" else brain),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()

    for generation in (1, 2):
        turn_context = replace(
            context(),
            generation=generation,
            turn_id=f"turn-{generation}",
        )
        await conversation.send(
            AppendItem(
                command_id=f"append-{generation}",
                idempotency_key=f"append-{generation}",
                context=turn_context,
                draft=ConversationItemDraft(
                    item_id=f"user-{generation}",
                    context=turn_context,
                    kind=ConversationItemKind.USER_INPUT,
                    status=ConversationItemStatus.COMPLETED,
                    producer="test",
                    content=(TextContent(f"第{generation}轮"),),
                ),
            )
        )
        while not isinstance(await anext(events), ItemProjected):
            pass
        if cache_mode == "speech_prepared" and generation == 1:
            turn = await core._turn_for_prefetch("第1轮", generation)
            await brain.prepare(turn)
        await conversation.send(
            RequestResponse(
                command_id=f"response-{generation}",
                idempotency_key=f"response-{generation}",
                context=turn_context,
                response_id=f"response-{generation}",
                minimum_thread_sequence=generation,
                output_item_id=f"assistant-{generation}",
            )
        )
        terminal = await asyncio.wait_for(anext(events), timeout=0.2)
        while not isinstance(terminal, (ResponseCompleted, ResponseFailed)):
            terminal = await asyncio.wait_for(anext(events), timeout=0.2)
        if generation == 1:
            assert isinstance(terminal, ResponseFailed)
            assert "accepted text" in terminal.error
        else:
            assert isinstance(terminal, ResponseCompleted)

    await conversation.close()


async def test_cascaded_response_deadline_fails_and_cancels_stalled_brain() -> None:
    brain = HangingBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
        response_timeout_s=0.02,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-timeout-user",
            idempotency_key="append-timeout-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="timeout-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试响应超时"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="timeout-response",
            idempotency_key="timeout-response",
            context=context(),
            response_id="timeout-response",
            minimum_thread_sequence=1,
        )
    )

    emitted = []
    while len(emitted) < 5:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, ResponseFailed):
            break
    failed = emitted[-1]
    assert isinstance(failed, ResponseFailed)
    assert failed.error == "response deadline exceeded after 0.020s"
    capability_failure = next(
        event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
    )
    assert capability_failure.capability == "response_deadline"
    await asyncio.wait_for(brain.cancelled.wait(), timeout=0.2)
    assert core._response_task is None

    await conversation.close()


async def test_cascaded_first_text_deadline_fails_before_total_response_timeout() -> None:
    brain = HangingBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
        response_timeout_s=1,
        response_first_text_timeout_s=0.02,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-first-text-timeout-user",
            idempotency_key="append-first-text-timeout-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="first-text-timeout-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("你好呀"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="first-text-timeout-response",
            idempotency_key="first-text-timeout-response",
            context=context(),
            response_id="first-text-timeout-response",
            minimum_thread_sequence=1,
        )
    )

    emitted = []
    while len(emitted) < 5:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, ResponseFailed):
            break
    failed = emitted[-1]
    assert isinstance(failed, ResponseFailed)
    assert failed.error == "first response text deadline exceeded after 0.020s"
    capability_failure = next(
        event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
    )
    assert capability_failure.capability == "response_first_text_deadline"
    await asyncio.wait_for(brain.cancelled.wait(), timeout=0.2)

    await conversation.close()


async def test_provider_timeout_is_not_misreported_as_response_deadline() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=ProviderTimeoutBrainProvider(),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
        response_timeout_s=1,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-provider-timeout-user",
            idempotency_key="append-provider-timeout-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="provider-timeout-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试服务内部超时"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="provider-timeout-response",
            idempotency_key="provider-timeout-response",
            context=context(),
            response_id="provider-timeout-response",
            minimum_thread_sequence=1,
        )
    )

    failed = await asyncio.wait_for(anext(events), timeout=0.2)

    assert isinstance(failed, ResponseFailed)
    assert failed.error == "model provider timed out"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(events), timeout=0.02)

    await conversation.close()


async def test_projected_tool_result_resumes_the_same_cascaded_response() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(PausingToolBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(TimeoutOnIdleTts()),
        response_first_text_timeout_s=0.05,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user",
            idempotency_key="append-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("现在几点"),),
            ),
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ItemProjected)
    response_context = replace(context(), response_id="response-1")
    await conversation.send(
        RequestResponse(
            command_id="response-1",
            idempotency_key="response-1",
            context=response_context,
            response_id="response-1",
            minimum_thread_sequence=1,
            output_item_id="assistant-1",
        )
    )
    assert isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), ResponseStarted
    )
    requested = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(requested, (ToolRequested, ResponseFailed)):
        requested = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(requested, ToolRequested)
    assert requested.call_id == "call-1"
    assert requested.latency is LatencyClass.FAST

    # Confirmation may outlast the first-text deadline without opening an idle TTS stream.
    await asyncio.sleep(0.08)

    tool_context = replace(
        context(),
        response_id="response-1",
        call_id="call-1",
    )
    await conversation.send(
        AppendItem(
            command_id="append-tool-result",
            idempotency_key="append-tool-result",
            context=tool_context,
            draft=ConversationItemDraft(
                item_id="tool-result-1",
                context=tool_context,
                kind=ConversationItemKind.TOOL_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="voice-runtime-tool-controller",
                content=(TextContent("12:30"),),
            ),
        )
    )

    emitted = []
    while len(emitted) < 12:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, ResponseCompleted):
            break
    assert any(isinstance(event, ItemProjected) for event in emitted)
    assert "".join(
        event.delta for event in emitted if isinstance(event, DisplayContentDelta)
    ) == "现在是12:30。"
    assert isinstance(emitted[-1], ResponseCompleted)
    await conversation.close()


async def test_cascaded_engine_projects_brain_delegation_as_untrusted_proposal() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(DelegatingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-delegation-user",
            idempotency_key="append-delegation-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="delegation-user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("后台检查项目"),),
            ),
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ItemProjected)
    await conversation.send(
        RequestResponse(
            command_id="delegation-response",
            idempotency_key="delegation-response",
            context=replace(context(), response_id="response-delegation"),
            response_id="response-delegation",
            minimum_thread_sequence=1,
            output_item_id="delegation-assistant-1",
        )
    )

    proposed = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(proposed, AgentDelegationRequestProposed):
        proposed = await asyncio.wait_for(anext(events), timeout=0.2)
    assert proposed.delegation_request_id == "delegation-1"
    assert proposed.context.worker_id is None
    assert proposed.agent_name == "codex"
    await conversation.close()


async def test_late_tool_result_from_cancelled_response_is_history_only() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(PausingToolBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user-before-cancel",
            idempotency_key="append-user-before-cancel",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-before-cancel",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("现在几点"),),
            ),
        )
    )
    await asyncio.wait_for(anext(events), timeout=0.2)
    response_context = replace(context(), response_id="cancelled-response")
    await conversation.send(
        RequestResponse(
            command_id="cancelled-response",
            idempotency_key="cancelled-response",
            context=response_context,
            response_id="cancelled-response",
            minimum_thread_sequence=1,
        )
    )
    while True:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        if isinstance(event, ToolRequested):
            break
    await conversation.send(
        CancelResponse(
            command_id="cancel-before-tool-result",
            idempotency_key="cancel-before-tool-result",
            context=response_context,
            response_id="cancelled-response",
            reason="text_barge_in",
        )
    )
    while True:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        if isinstance(event, ResponseCancelled):
            break

    tool_context = replace(
        context(),
        response_id="cancelled-response",
        call_id="call-1",
    )
    await conversation.send(
        AppendItem(
            command_id="late-tool-result",
            idempotency_key="late-tool-result",
            context=tool_context,
            draft=ConversationItemDraft(
                item_id="late-tool-result",
                context=tool_context,
                kind=ConversationItemKind.TOOL_RESULT,
                status=ConversationItemStatus.CANCELLED,
                producer="test-tool-loop",
                content=(TextContent("工具执行已取消。"),),
            ),
        )
    )

    while True:
        projected = await asyncio.wait_for(anext(events), timeout=0.2)
        if isinstance(projected, ItemProjected):
            break
    assert projected.item_id == "late-tool-result"
    await conversation.close()


async def test_user_follow_up_projects_an_inflight_tool_request_before_itself() -> None:
    journal = InMemoryConversationJournal()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=core,
    )
    events = conversation.events()

    await conversation.send(
        AppendItem(
            command_id="append-initial-user",
            idempotency_key="append-initial-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="initial-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("北京今天天气怎么样？"),),
            ),
        )
    )
    assert (await asyncio.wait_for(anext(events), timeout=0.2)).thread_sequence == 1

    tool_context = replace(
        context(),
        response_id="response-weather",
        call_id="call-weather",
    )
    await journal.append(
        ConversationItemDraft(
            item_id="tool-request-weather",
            context=tool_context,
            kind=ConversationItemKind.TOOL_REQUESTED,
            status=ConversationItemStatus.COMPLETED,
            producer="test-tool-loop",
            content=(TextContent("weather"),),
        )
    )
    follow_up_context = replace(context(), turn_id="turn-2", generation=2)

    await conversation.send(
        AppendItem(
            command_id="append-follow-up",
            idempotency_key="append-follow-up",
            context=follow_up_context,
            draft=ConversationItemDraft(
                item_id="follow-up-user",
                context=follow_up_context,
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("补充一下明天的。"),),
            ),
        )
    )

    projected = [
        await asyncio.wait_for(anext(events), timeout=0.2),
        await asyncio.wait_for(anext(events), timeout=0.2),
    ]
    assert [event.thread_sequence for event in projected] == [2, 3]
    assert [event.item_id for event in projected] == [
        "tool-request-weather",
        "follow-up-user",
    ]
    await conversation.close()


async def test_follow_up_brain_turn_contains_bounded_projected_conversation_context() -> None:
    brain = RecordingContextBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()

    for generation, item_id, text in (
        (1, "weather-user", "北京今天天气怎么样？"),
        (2, "weather-follow-up", "补充一下明天的。"),
    ):
        turn_context = replace(
            context(),
            generation=generation,
            turn_id=f"turn-{generation}",
        )
        await conversation.send(
            AppendItem(
                command_id=f"append-{item_id}",
                idempotency_key=f"append-{item_id}",
                context=turn_context,
                draft=ConversationItemDraft(
                    item_id=item_id,
                    context=turn_context,
                    kind=ConversationItemKind.USER_INPUT,
                    status=ConversationItemStatus.COMPLETED,
                    producer="test",
                    content=(TextContent(text),),
                ),
            )
        )
        projected = await asyncio.wait_for(anext(events), timeout=0.2)
        response_id = f"response-{generation}"
        await conversation.send(
            RequestResponse(
                command_id=response_id,
                idempotency_key=response_id,
                context=replace(turn_context, response_id=response_id),
                response_id=response_id,
                minimum_thread_sequence=projected.thread_sequence,
            )
        )
        while True:
            event = await asyncio.wait_for(anext(events), timeout=0.2)
            if isinstance(event, ResponseCompleted):
                break

    assert brain.turns[1].text == "补充一下明天的。"
    assert brain.turns[1].conversation_context == "用户：北京今天天气怎么样？"
    await conversation.close()


async def test_follow_up_context_contains_only_the_interrupted_assistant_prefix_heard() -> None:
    """Cascaded projection mirrors Realtime conversation.item.truncate semantics."""

    brain = RecordingContextBrain()
    deliveries = InMemorySpeechDeliveryStore()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    journal = InMemoryConversationJournal()
    conversation = JournaledRealtimeConversation(
        context=context(), journal=journal, engine_conversation=core
    )
    events = conversation.events()

    async def append(item_id: str, item_context: InteractionContext, kind, text: str):
        await conversation.send(
            AppendItem(
                command_id=f"append-{item_id}",
                idempotency_key=f"append-{item_id}",
                context=item_context,
                draft=ConversationItemDraft(
                    item_id=item_id,
                    context=item_context,
                    kind=kind,
                    status=(
                        ConversationItemStatus.INTERRUPTED
                        if kind is ConversationItemKind.ASSISTANT_OUTPUT
                        else ConversationItemStatus.COMPLETED
                    ),
                    producer="test",
                    content=(TextContent(text),),
                ),
            )
        )
        return await asyncio.wait_for(anext(events), timeout=0.2)

    await append("weather-question", context(), ConversationItemKind.USER_INPUT, "哪个城市？")
    assistant_context = replace(context(), response_id="clarification-response")
    await deliveries.start(
        SpeechDeliveryRecord(
            speech_id="response:clarification-response",
            context=assistant_context,
            source_item_id="assistant-clarification",
            context_policy=SpeechContextPolicy.AUTO,
            interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
        )
    )
    await deliveries.append_text(
        "response:clarification-response",
        "请告诉我想查询哪个城市的天气。",
    )
    await deliveries.commit_text("response:clarification-response")
    await deliveries.report_progress(
        "response:clarification-response",
        delivered_text_end=len("请告诉我"),
        played_audio_end_us=520_000,
        precision=PlaybackPrecision.EXACT,
        completed=False,
    )
    await deliveries.cancel(
        "response:clarification-response",
        reason="barge_in_floor_claim",
    )
    await append(
        "assistant-clarification",
        assistant_context,
        ConversationItemKind.ASSISTANT_OUTPUT,
        "请告诉我想查询哪个城市的天气。",
    )
    follow_up_context = replace(context(), turn_id="turn-2", generation=2)
    projected = await append(
        "city-follow-up",
        follow_up_context,
        ConversationItemKind.USER_INPUT,
        "北京的",
    )
    await conversation.send(
        RequestResponse(
            command_id="respond-follow-up",
            idempotency_key="respond-follow-up",
            context=replace(follow_up_context, response_id="follow-up-response"),
            response_id="follow-up-response",
            minimum_thread_sequence=projected.thread_sequence,
        )
    )
    while not isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2),
        ResponseCompleted,
    ):
        pass

    assert brain.turns[0].text == "北京的"
    assert brain.turns[0].conversation_context == (
        "用户：哪个城市？\n助手：请告诉我"
    )
    stored = await journal.read(JournalScope.from_context(context()))
    assistant = next(
        item for item in stored if item.item_id == "assistant-clarification"
    )
    assert assistant.content == (TextContent("请告诉我想查询哪个城市的天气。"),)
    await conversation.close()


async def test_variable_weather_tool_ack_is_followed_by_final_response() -> None:
    journal = InMemoryConversationJournal()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(PausingVariableToolBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
        response_timeout_s=1,
    ).open(context=context(), profile=None)
    journaled = JournaledRealtimeConversation(
        context=context(),
        journal=journal,
        engine_conversation=core,
    )

    async def weather(arguments: dict) -> str:
        assert arguments == {"city": "Shanghai"}
        return "晴，25°C"

    tools = registry(weather, latency=LatencyClass.VARIABLE)
    gateway = DefaultToolPolicyGateway(tools)

    def tool_handler() -> DefaultToolControlHandler:
        return DefaultToolControlHandler(
            loop=FastToolLoop(
                gateway=gateway,
                executor=ToolExecutor(tools, gateway),
                journal=journal,
            ),
            policy_context=ToolPolicyContext(),
        )

    conversation = RealtimeToolController(
        context=context(),
        conversation=journaled,
        committed_projection=core,
        tool_control_handler_factory=tool_handler,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user-weather",
            idempotency_key="append-user-weather",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-weather",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("今天天气怎么样"),),
            ),
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ItemProjected)
    response_context = replace(context(), response_id="response-weather")
    await conversation.send(
        RequestResponse(
            command_id="response-weather",
            idempotency_key="response-weather",
            context=response_context,
            response_id="response-weather",
            minimum_thread_sequence=1,
            output_item_id="assistant-weather",
        )
    )

    emitted = []
    while not any(isinstance(event, ResponseCompleted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=1))

    assert "".join(
        event.delta for event in emitted if isinstance(event, DisplayContentDelta)
    ) == "我查一下，马上告诉你。今天天气晴，25°C。"
    items = await journal.read(JournalScope.from_context(context()))
    assert [item.kind for item in items] == [
        ConversationItemKind.USER_INPUT,
        ConversationItemKind.TOOL_REQUESTED,
        ConversationItemKind.TOOL_RESULT,
    ]
    assert [item.sequence for item in items] == [1, 2, 3]
    assert not any(isinstance(event, RealtimeCapabilityFailed) for event in emitted)
    await conversation.close()


async def test_duplex_tts_emits_audio_before_brain_text_stream_completes() -> None:
    brain = GatedStreamingBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user-1",
            idempotency_key="append-user-1",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试双流式"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="response-1",
            idempotency_key="response-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )

    try:
        before_release = []
        async with asyncio.timeout(.2):
            while len(before_release) < 4:
                event = await anext(events)
                assert not isinstance(event, (ResponseCompleted, ResponseFailed))
                if isinstance(event, (ResponseStarted, DisplayContentDelta, SpokenContentDelta, AudioDelta)):
                    before_release.append(event)
        # Actor state diagnostics can interleave; the four actual output facts
        # still precede model completion and retain their required order.
        assert isinstance(before_release[0], ResponseStarted)
        assert isinstance(before_release[1], DisplayContentDelta)
        assert isinstance(before_release[2], SpokenContentDelta)
        assert isinstance(before_release[3], AudioDelta)
        assert before_release[3].frame.data == "第一段".encode()

        brain.release.set()
        while not isinstance(await anext(events), ResponseCompleted):
            pass
    finally:
        brain.release.set()
        await conversation.close()


async def test_cancel_response_stops_brain_and_tts_with_one_cancelled_terminal() -> None:
    brain = GatedStreamingBrain()
    deliveries = InMemorySpeechDeliveryStore()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user",
            idempotency_key="append-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试取消"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="response",
            idempotency_key="response",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
            output_item_id="assistant-1",
        )
    )
    before_cancel = []
    while not any(isinstance(event, AudioDelta) for event in before_cancel):
        before_cancel.append(await asyncio.wait_for(anext(events), timeout=0.2))
    await conversation.send(
        ReportPlaybackProgress(
            command_id="playback",
            idempotency_key="playback",
            context=context(),
            speech_id="response:response-1",
            delivered_text_end=len("第一段"),
            played_audio_end_us=320_000,
        )
    )
    playback_event = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(playback_event, SpeechPlaybackProgress):
        playback_event = await asyncio.wait_for(anext(events), timeout=0.2)

    await asyncio.wait_for(
        conversation.send(
            CancelResponse(
                command_id="cancel-response",
                idempotency_key="cancel-response",
                context=context(),
                response_id="response-1",
                reason="barge_in",
            )
        ),
        timeout=0.2,
    )
    cancelled = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(cancelled, ResponseCancelled):
        cancelled = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(cancelled, ResponseCancelled)
    assert cancelled.reason == "barge_in"
    assert not any(isinstance(event, ResponseCompleted) for event in before_cancel)
    delivery = await deliveries.latest_for_item("assistant-1")
    assert delivery is not None
    assert delivery.status is SpeechDeliveryStatus.INTERRUPTED
    assert delivery.delivered_speech_transcript == "第一段"
    await conversation.close()


async def test_floor_claim_commits_new_turn_when_duplex_tts_cleanup_stalls() -> None:
    tts = SlowCancellationDuplexTts()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("我来补充一句")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=FloorClaimClassifier(),
            asr_idle_stop_ms=32,
        ),
        brain=LegacyBrainCapabilityAdapter(GatedStreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(tts),
    ).open(context=context(), profile=None)
    journaled = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    conversation = RealtimeTurnController(
        context=context(),
        conversation=journaled,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-playing-user",
            idempotency_key="append-playing-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="playing-user",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("先说一段很长的话"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="playing-response",
            idempotency_key="playing-response",
            context=context(),
            response_id="playing-response",
            minimum_thread_sequence=1,
        )
    )
    while not isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2), AudioDelta
    ):
        pass

    overlap = replace(context(), turn_id="turn-2", generation=2)
    await conversation.send(
        AppendAudio(
            command_id="overlap-onset",
            idempotency_key="overlap-onset",
            context=overlap,
            frame=pcm_frame(sequence=0, amplitude=1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="overlap-stop",
            idempotency_key="overlap-stop",
            context=overlap,
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )

    try:
        emitted = []
        while not any(isinstance(event, InputTranscriptCompleted) for event in emitted):
            emitted.append(await asyncio.wait_for(anext(events), timeout=0.7))
        assert any(isinstance(event, AssistantYieldRequested) for event in emitted)
        assert any(isinstance(event, ResponseCancelled) for event in emitted)
        cleanup_timeout = next(
            event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
        )
        assert cleanup_timeout.capability == "tts_cancel_cleanup"
        transcript = next(
            event for event in emitted if isinstance(event, InputTranscriptCompleted)
        )
        assert transcript.text == "我来补充一句"

        next_response = []
        while not any(isinstance(event, ResponseFailed) for event in next_response):
            next_response.append(
                await asyncio.wait_for(anext(events), timeout=0.2)
            )
        failure = next(event for event in next_response if isinstance(event, ResponseFailed))
        assert "requires a new capability session" in failure.error
        assert not any(isinstance(event, (ResponseStarted, DisplayContentDelta, AudioDelta)) for event in next_response)
        assert core._tts_cleanup_unconfirmed
        assert core._projected_items[max(core._projected_items)].content == (TextContent("我来补充一句"),)
    finally:
        tts.cleanup_release.set()
        await conversation.close()


async def test_cancel_response_is_safe_immediately_after_request_admission() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(GatedStreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user",
            idempotency_key="append-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("立即取消"),),
            ),
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ItemProjected)
    await conversation.send(
        RequestResponse(
            command_id="response",
            idempotency_key="response",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )

    await conversation.send(
        CancelResponse(
            command_id="cancel-response",
            idempotency_key="cancel-response",
            context=context(),
            response_id="response-1",
            reason="superseded",
        )
    )

    cancelled = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(cancelled, ResponseCancelled)
    assert cancelled.reason == "superseded"
    await conversation.close()


async def test_cancel_response_emits_terminal_when_provider_cleanup_propagates_cancel() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=CancellationPropagatingBrainProvider(),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user",
            idempotency_key="append-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("取消兜底"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="response",
            idempotency_key="response",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )
    while not isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2),
        DisplayContentDelta,
    ):
        pass

    await conversation.send(
        CancelResponse(
            command_id="cancel-response",
            idempotency_key="cancel-response",
            context=context(),
            response_id="response-1",
            reason="barge_in_floor_claim",
        )
    )

    terminal = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(terminal, ResponseCancelled):
        terminal = await asyncio.wait_for(anext(events), timeout=0.2)
    assert terminal.response_id == "response-1"
    assert terminal.reason == "barge_in_floor_claim"
    await conversation.close()


async def test_cancel_response_detaches_stalled_brain_cleanup_and_emits_one_terminal() -> None:
    brain = SlowCancellationBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
        response_cancel_timeout_s=0.02,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-user",
            idempotency_key="append-user",
            context=context(),
            draft=ConversationItemDraft(
                item_id="user-1",
                context=context(),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED,
                producer="test",
                content=(TextContent("测试有界取消"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        RequestResponse(
            command_id="response",
            idempotency_key="response",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=1,
        )
    )
    while not isinstance(
        await asyncio.wait_for(anext(events), timeout=0.2),
        DisplayContentDelta,
    ):
        pass

    try:
        await asyncio.wait_for(
            conversation.send(
                CancelResponse(
                    command_id="cancel-response",
                    idempotency_key="cancel-response",
                    context=context(),
                    response_id="response-1",
                    reason="barge_in_floor_claim",
                )
            ),
            timeout=0.2,
        )
        emitted = []
        while not any(isinstance(event, ResponseCancelled) for event in emitted):
            emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
        assert sum(isinstance(event, ResponseCancelled) for event in emitted) == 1
        failure = next(
            event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
        )
        assert failure.capability == "response_cancel_cleanup"
        assert core._response_task is None
    finally:
        brain.cleanup_release.set()
        await conversation.close()


async def test_external_speech_text_streams_directly_into_duplex_tts() -> None:
    conversation = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    events = conversation.events()

    await conversation.send(
        StartSpeech(
            command_id="speech-start",
            idempotency_key="speech-start",
            context=context(),
            speech_id="speech-1",
        )
    )
    assert isinstance(await anext(events), SpeechStarted)

    await conversation.send(
        AppendSpeechText(
            command_id="speech-text-1",
            idempotency_key="speech-text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="第一段，",
        )
    )
    accepted = await anext(events)
    audio_delta = await anext(events)
    assert isinstance(accepted, SpeechTextAccepted)
    assert isinstance(audio_delta, SpeechAudioDelta)
    assert audio_delta.speech_id == "speech-1"
    assert audio_delta.frame.data == "第一段，".encode()

    await conversation.send(
        AppendSpeechText(
            command_id="speech-text-2",
            idempotency_key="speech-text-2",
            context=context(),
            speech_id="speech-1",
            text_sequence=2,
            delta="第二段。",
        )
    )
    await conversation.send(
        CommitSpeech(
            command_id="speech-commit",
            idempotency_key="speech-commit",
            context=context(),
            speech_id="speech-1",
        )
    )

    emitted = []
    while len(emitted) < 8:
        event = await anext(events)
        emitted.append(event)
        if isinstance(event, SpeechAudioCompleted):
            break
    assert any(isinstance(event, SpeechTextCommitted) for event in emitted)
    assert b"".join(
        event.frame.data for event in emitted if isinstance(event, SpeechAudioDelta)
    ) == "第二段。".encode()
    spoken_text = "第一段，第二段。"
    await conversation.send(
        ReportPlaybackProgress(
            command_id="speech-playback",
            idempotency_key="speech-playback",
            context=context(),
            speech_id="speech-1",
            delivered_text_end=len(spoken_text),
            played_audio_end_us=800_000,
            completed=True,
        )
    )
    playback = await anext(events)
    assert isinstance(playback, SpeechPlaybackProgress)
    assert playback.delivered_speech_transcript == spoken_text
    await conversation.close()


async def test_cancelled_external_speech_releases_tts_lane_before_returning() -> None:
    conversation = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="speech-start",
            idempotency_key="speech-start",
            context=context(),
            speech_id="speech-1",
        )
    )
    await anext(events)
    await conversation.send(
        AppendSpeechText(
            command_id="speech-text",
            idempotency_key="speech-text",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="还没说完",
        )
    )
    audio_delta = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(audio_delta, SpeechAudioDelta):
        audio_delta = await asyncio.wait_for(anext(events), timeout=0.2)

    await conversation.send(
        CancelSpeech(
            command_id="speech-cancel",
            idempotency_key="speech-cancel",
            context=context(),
            speech_id="speech-1",
            reason="barge_in",
        )
    )
    cancelled = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(cancelled, SpeechCancelled):
        cancelled = await asyncio.wait_for(anext(events), timeout=0.2)

    await conversation.send(
        StartSpeech(
            command_id="speech-start-2",
            idempotency_key="speech-start-2",
            context=context(),
            speech_id="speech-2",
        )
    )
    restarted = await asyncio.wait_for(anext(events), timeout=0.2)
    while not isinstance(restarted, SpeechStarted):
        restarted = await asyncio.wait_for(anext(events), timeout=0.2)
    assert restarted.speech_id == "speech-2"
    await conversation.close()


async def test_floor_claim_cancels_external_speech_before_committing_user_turn() -> None:
    conversation = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("我来接着说")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=FloorClaimClassifier(),
        ),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="speech-start",
            idempotency_key="speech-start",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="speech-text",
            idempotency_key="speech-text",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="一段很长的主动播报",
        )
    )
    while not isinstance(await anext(events), SpeechAudioDelta):
        pass

    overlap = replace(context(), turn_id="turn-2", generation=2)
    await conversation.send(
        AppendAudio(
            command_id="overlap-1",
            idempotency_key="overlap-1",
            context=overlap,
            frame=pcm_frame(sequence=0, amplitude=1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="overlap-2",
            idempotency_key="overlap-2",
            context=overlap,
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )

    emitted = []
    while not any(isinstance(event, InputTranscriptCompleted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert any(isinstance(event, AssistantYieldRequested) for event in emitted)
    assert any(isinstance(event, SpeechCancelled) for event in emitted)
    transcript = next(
        event for event in emitted if isinstance(event, InputTranscriptCompleted)
    )
    assert transcript.text == "我来接着说"
    await conversation.close()


async def test_external_tts_failure_settles_delivery_record_as_failed() -> None:
    deliveries = InMemorySpeechDeliveryStore()
    conversation = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(FailingDuplexTts()),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="speech-start",
            idempotency_key="speech-start",
            context=context(),
            speech_id="speech-1",
        )
    )
    await anext(events)
    await conversation.send(
        AppendSpeechText(
            command_id="speech-text",
            idempotency_key="speech-text",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="会失败",
        )
    )
    await anext(events)
    failed = await anext(events)

    assert isinstance(failed, RealtimeCapabilityFailed)
    record = await deliveries.get("speech-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.FAILED
    assert record.reason == "TTS websocket disconnected"
    await conversation.close()


async def test_deliver_item_defaults_to_model_response_after_projection() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(AgentResultBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent-task-supervisor",
                content=(TextContent("后台任务已完成"),),
            ),
        )
    )
    await anext(events)

    await conversation.send(
        DeliverItem(
            command_id="deliver-result",
            idempotency_key="deliver-result",
            context=replace(context(), response_id="previous-response"),
            item_id="result-1",
            delivery_id="delivery-result",
        )
    )

    emitted = []
    while len(emitted) < 20:
        event = await anext(events)
        emitted.append(event)
        if isinstance(event, ItemDeliveryCompleted):
            break
    assert isinstance(emitted[0], ItemDeliveryQueued)
    assert isinstance(emitted[1], ItemDeliveryStarted)
    assert any(isinstance(event, ResponseStarted) for event in emitted)
    assert "".join(
        event.delta for event in emitted if isinstance(event, SpokenContentDelta)
    ) == "任务结果已经准备好了。"
    assert isinstance(emitted[-1], ItemDeliveryCompleted)

    await conversation.close()


async def test_failed_model_response_marks_item_delivery_failed_not_completed() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(FailingBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent-task-supervisor",
                content=(TextContent("后台任务已完成"),),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="deliver-result",
            idempotency_key="deliver-result",
            context=context(),
            item_id="result-1",
            delivery_id="delivery-result",
        )
    )

    emitted = []
    while len(emitted) < 12:
        event = await anext(events)
        emitted.append(event)
        if isinstance(event, ItemDeliveryFailed):
            break

    assert any(isinstance(event, ResponseFailed) for event in emitted)
    capability_failure = next(
        event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
    )
    assert capability_failure.capability == "brain"
    assert not any(isinstance(event, ItemDeliveryCompleted) for event in emitted)
    assert emitted[-1].error == "model service timed out"
    await conversation.close()


async def test_display_speech_and_silent_delivery_modes_do_not_call_brain() -> None:
    class BrainMustNotRun:
        async def stream(self, turn) -> AsyncIterator[str]:
            raise AssertionError(f"Brain must not run for direct delivery: {turn.text}")
            yield ""

    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(BrainMustNotRun()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent-task-supervisor",
                content=(TextContent("完整结果"),),
                display=DisplayContent(markdown="## 完整结果"),
                spoken=SpokenContent(text="任务完成。"),
            ),
        )
    )
    await anext(events)

    await conversation.send(
        DeliverItem(
            command_id="display-result",
            idempotency_key="display-result",
            context=context(),
            item_id="result-1",
            delivery_id="display-result",
            mode=DeliveryMode.DISPLAY_ONLY,
        )
    )
    display_events = [await anext(events) for _ in range(4)]
    assert isinstance(display_events[2], ItemDisplayPresented)
    assert display_events[2].markdown == "## 完整结果"
    assert isinstance(display_events[3], ItemDeliveryCompleted)

    await conversation.send(
        DeliverItem(
            command_id="speak-result",
            idempotency_key="speak-result",
            context=context(),
            item_id="result-1",
            delivery_id="speak-result",
            mode=DeliveryMode.SPEECH,
        )
    )
    speech_events = []
    while len(speech_events) < 12:
        event = await anext(events)
        speech_events.append(event)
        if isinstance(event, ItemDeliveryCompleted):
            break
    assert "".join(
        event.delta for event in speech_events if isinstance(event, SpokenContentDelta)
    ) == "任务完成。"
    assert b"".join(
        event.frame.data for event in speech_events if isinstance(event, AudioDelta)
    ) == "任务完成。".encode()

    await conversation.send(
        DeliverItem(
            command_id="silent-result",
            idempotency_key="silent-result",
            context=context(),
            item_id="result-1",
            delivery_id="silent-result",
            mode=DeliveryMode.SILENT,
        )
    )
    silent_events = [await anext(events) for _ in range(3)]
    assert isinstance(silent_events[-1], ItemDeliveryCompleted)

    await conversation.close()


async def test_direct_speech_tts_failure_marks_response_and_delivery_failed() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(FailingDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent-task-supervisor",
                content=(TextContent("任务完成"),),
                spoken=SpokenContent(text="任务完成。"),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="speak-result",
            idempotency_key="speak-result",
            context=context(),
            item_id="result-1",
            delivery_id="speak-result",
            mode=DeliveryMode.SPEECH,
        )
    )

    emitted = []
    while len(emitted) < 10:
        event = await asyncio.wait_for(anext(events), timeout=0.2)
        emitted.append(event)
        if isinstance(event, ItemDeliveryFailed):
            break

    assert any(isinstance(event, ResponseFailed) for event in emitted)
    capability_failure = next(
        event for event in emitted if isinstance(event, RealtimeCapabilityFailed)
    )
    assert capability_failure.capability == "tts"
    assert not any(isinstance(event, ItemDeliveryCompleted) for event in emitted)
    assert emitted[-1].error == "TTS websocket disconnected"
    # Browser playback notifications may already be queued when TTS fails.
    await conversation.send(
        ReportPlaybackProgress(
            command_id="late-playback-start",
            idempotency_key="late-playback-start",
            context=context(),
            speech_id="response:delivery:speak-result",
            delivered_text_end=0,
            played_audio_end_us=0,
            completed=False,
        )
    )
    await conversation.close()


async def test_cancel_response_cancels_direct_item_speech_delivery() -> None:
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(GatedDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent",
                content=(TextContent("后台结果"),),
                spoken=SpokenContent("后台结果已经完成。"),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="deliver",
            idempotency_key="deliver",
            context=context(),
            item_id="result-1",
            delivery_id="delivery-1",
            mode=DeliveryMode.SPEECH,
        )
    )
    while not isinstance(await anext(events), AudioDelta):
        pass

    await conversation.send(
        CancelResponse(
            command_id="cancel-delivery",
            idempotency_key="cancel-delivery",
            context=context(),
            response_id="delivery:delivery-1",
            reason="reconfiguration",
        )
    )

    emitted = []
    while not any(isinstance(event, ItemDeliveryCancelled) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert any(isinstance(event, ResponseCancelled) for event in emitted)
    assert not any(isinstance(event, ItemDeliveryCompleted) for event in emitted)
    await conversation.close()


async def test_floor_claim_cancels_direct_item_speech_delivery() -> None:
    tts = GatedDuplexTts()
    deliveries = InMemorySpeechDeliveryStore()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("换我说")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=FloorClaimClassifier(),
        ),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(tts),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(
        context=context(),
        journal=InMemoryConversationJournal(),
        engine_conversation=core,
    )
    events = conversation.events()
    await conversation.send(
        AppendItem(
            command_id="append-result",
            idempotency_key="append-result",
            context=context(),
            draft=ConversationItemDraft(
                item_id="result-1",
                context=context(),
                kind=ConversationItemKind.DELEGATION_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="agent",
                content=(TextContent("后台结果"),),
                spoken=SpokenContent("后台结果已经完成。"),
            ),
        )
    )
    await anext(events)
    await conversation.send(
        DeliverItem(
            command_id="deliver",
            idempotency_key="deliver",
            context=context(),
            item_id="result-1",
            delivery_id="delivery-1",
            mode=DeliveryMode.SPEECH,
        )
    )
    while not isinstance(await anext(events), AudioDelta):
        pass

    overlap = replace(context(), turn_id="turn-2", generation=2)
    await conversation.send(
        AppendAudio(
            command_id="overlap-1",
            idempotency_key="overlap-1",
            context=overlap,
            frame=pcm_frame(sequence=0, amplitude=1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="overlap-2",
            idempotency_key="overlap-2",
            context=overlap,
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )
    emitted = []
    while not any(isinstance(event, ItemDeliveryCancelled) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert any(isinstance(event, ResponseCancelled) for event in emitted)
    assert not any(isinstance(event, ItemDeliveryCompleted) for event in emitted)
    delivery = await deliveries.latest_for_item("result-1")
    assert delivery is not None
    assert delivery.status is SpeechDeliveryStatus.INTERRUPTED
    await conversation.close()


async def test_resolved_profile_audio_processor_runs_before_vad_and_asr() -> None:
    registry = PluginRegistry()
    registry.register(
        PluginManifest(
            plugin_id="test.gain",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.AUDIO_PROCESSOR,
            contract_version=1,
            placement=PluginPlacement.IN_PROCESS,
            capabilities=frozenset({"audio_gain"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=20,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
            allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
            default_failure_policy=FailurePolicy.FAIL,
        ),
        binding=GainProcessorBinding(),
    )
    profile = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.AUDIO_PROCESSOR,
                    plugin_id="test.gain",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset({DataGrant.INPUT_AUDIO_RAW}),
                    config={"gain": 10},
                ),
            ),
        )
    )
    conversation = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("插件链生效")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(SilentTts()),
        pseudonymization_key="test-key",
    ).open(context=context(), profile=profile)
    events = conversation.events()

    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=context(),
            frame=pcm_frame(sequence=0, amplitude=100),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="audio-2",
            idempotency_key="audio-2",
            context=context(),
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )

    emitted = []
    while not any(
        isinstance(event, InputTranscriptCompleted) for event in emitted
    ):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    completed = next(
        event for event in emitted if isinstance(event, InputTranscriptCompleted)
    )
    assert completed.text == "插件链生效"
    await conversation.close()


async def test_resolved_profile_can_replace_and_configure_a_cascaded_capability() -> None:
    registry = PluginRegistry()
    configurable_vad = ConfigurableVadBinding()
    registry.register(
        PluginManifest(
            plugin_id="test.vad",
            plugin_version="1.0.0",
            plugin_kind=PluginKind.VAD,
            contract_version=1,
            placement=PluginPlacement.IN_PROCESS,
            capabilities=frozenset({"voice_activity_detection"}),
            audio_formats=(AudioFormat(AudioEncoding.PCM_S16LE, 16_000, 1),),
            latency_budget_ms=10,
            approved_data_grants=frozenset({DataGrant.INPUT_AUDIO_PROCESSED}),
            allowed_failure_policies=frozenset({FailurePolicy.FAIL}),
            default_failure_policy=FailurePolicy.FAIL,
        ),
        binding=configurable_vad,
    )
    profile = ProfileResolver(registry).resolve(
        RealtimeProfile(
            schema_version=1,
            engine_kind=EngineKind.CASCADED,
            plugins=(
                PluginSelection(
                    slot=PluginKind.VAD,
                    plugin_id="test.vad",
                    plugin_version="1.0.0",
                    requested_data_grants=frozenset(
                        {DataGrant.INPUT_AUDIO_PROCESSED}
                    ),
                    config={"threshold": 50},
                ),
            ),
        )
    )
    conversation = await engine().open(context=context(), profile=profile)
    events = conversation.events()

    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=context(),
            frame=pcm_frame(sequence=0, amplitude=100),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="audio-2",
            idempotency_key="audio-2",
            context=context(),
            frame=pcm_frame(sequence=1, amplitude=0),
        )
    )

    emitted = []
    while not any(
        isinstance(event, InputTranscriptCompleted) for event in emitted
    ):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert any(isinstance(event, InputTranscriptCompleted) for event in emitted)
    assert configurable_vad.received_config == {"threshold": 50}
    await conversation.close()

async def test_continuation_projection_replaces_user_text_without_losing_tool_facts():
    from server.conversation_journal.models import item_from_draft
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig(energy_threshold=500, silence_duration_ms=32))),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(SilentBrain()),
        speech_renderer=DeterministicSpeechRenderer(), tts=LegacyTtsCapabilityAdapter(SilentTts()),
    ).open(context=context(), profile=None)
    try:
        old = replace(context(), turn_id="old")
        new = replace(context(), turn_id="new", generation=2)
        for seq, ctx, kind, text_value, metadata in [
            (1, old, ConversationItemKind.USER_INPUT, "查天气", {}),
            (2, old, ConversationItemKind.TOOL_RESULT, "已查询北京天气", {}),
            (3, new, ConversationItemKind.USER_INPUT, "查天气\n还有明天", {"continuation_of_turn_id": "old"}),
        ]:
            core._projected_items[seq] = item_from_draft(
                ConversationItemDraft(item_id=f"item-{seq}", context=ctx, kind=kind,
                    status=ConversationItemStatus.COMPLETED, producer="test", content=(TextContent(text_value),),
                    provider_metadata=metadata), sequence=seq, recorded_at=datetime.now(UTC),
            )
        turn = await core._turn_from_projection(3, generation=2)
        assert turn.text == "查天气\n还有明天"
        assert "已查询北京天气" in turn.conversation_context
        assert "用户：查天气" not in turn.conversation_context
    finally:
        await core.close()

async def test_immediate_preparing_yield_cancels_the_admitted_response(monkeypatch):
    from server.realtime.capabilities.coordinated_turn_manager import (
        CoordinatedTurnManagerCapabilityAdapter,
    )
    from server.realtime.capabilities.turn_manager import AssistantYieldRequested as CapabilityYield
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(lambda: EnergyVad(EnergyVadConfig(energy_threshold=500, silence_duration_ms=32))),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=CoordinatedTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(GatedStreamingBrain()),
        speech_renderer=DeterministicSpeechRenderer(), tts=LegacyTtsCapabilityAdapter(EchoDuplexTts()),
    ).open(context=context(), profile=None)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(), engine_conversation=core)
    events = conversation.events()
    original = core._input_pipeline.response_started

    async def yield_on_preparing(response_id, *, context=None, preparing=False, repair=None):
        await original(response_id, context=context, preparing=preparing, repair=repair)
        if preparing:
            await core._input_pipeline._events.put(CapabilityYield(
                context=replace(context, response_id=response_id), reason="barge_in_floor_claim"))
            # Give the input pump a chance to process the preparing-time yield.
            await asyncio.sleep(0)
    monkeypatch.setattr(core._input_pipeline, "response_started", yield_on_preparing)
    try:
        await conversation.send(AppendItem(command_id="prepare-user", idempotency_key="prepare-user", context=context(),
            draft=ConversationItemDraft(item_id="prepare-user", context=context(), kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMPLETED, producer="test", content=(TextContent("查天气"),))))
        assert isinstance(await asyncio.wait_for(anext(events), .2), ItemProjected)
        await conversation.send(RequestResponse(command_id="prepare-response", idempotency_key="prepare-response",
            context=replace(context(), response_id="prepared"), response_id="prepared", minimum_thread_sequence=1))
        async with asyncio.timeout(.5):
            async for event in events:
                if isinstance(event, ResponseCancelled):
                    assert event.response_id == "prepared"
                    break
        assert core._active_response_id is None
    finally:
        await conversation.close()
