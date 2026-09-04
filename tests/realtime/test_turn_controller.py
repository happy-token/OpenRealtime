from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
)
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendAudio,
    AppendSpeechText,
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CommitSpeech,
    ItemProjected,
    JournaledRealtimeConversation,
    ReportPlaybackProgress,
    ResponseCancelled,
    ResponseCompleted,
    SpeechPlaybackProgress,
    SpeechTextCommitted,
    StartSpeech,
)
from server.realtime.capabilities import (
    DeterministicSpeechRenderer,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyTurnManagerCapabilityAdapter,
    LegacyVadCapabilityAdapter,
)
from server.realtime.cascaded import CascadedRealtimeEngine
from server.realtime.control_plane import RealtimeTurnController
from server.realtime.speech import InMemorySpeechDeliveryStore, SpeechDeliveryStatus
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import AsrSnapshot, PreloadedAsrEngine
from server.speech.tts import SynthesizedAudioChunk
from server.turn_policy.dual_intent import DualIntent
from server.turn_policy.policy import TurnPolicy


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


def audio(sequence: int, amplitude: int) -> AudioFrame:
    return AudioFrame(
        stream_id="input-1",
        sequence=sequence,
        timestamp_us=sequence * 32_000,
        duration_us=32_000,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate_hz=16_000,
        channels=1,
        data=array.array("h", [amplitude] * 512).tobytes(),
    )


class WeatherBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        assert turn.text == "明天上海天气怎么样"
        yield "明天上海有小雨，"
        yield "记得带伞。"


class EchoTts:
    async def synthesize_duplex(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for text in text_stream:
            yield SynthesizedAudioChunk(
                pcm16=text.encode(), sample_rate_hz=24_000, is_final=False
            )


class AlwaysFloorClaimClassifier:
    async def classify(self, *, generation: int, overlap_ms: float, text: str):
        del generation, overlap_ms, text
        return DualIntent.FLOOR_CLAIM


class BargeInBrain:
    def __init__(self) -> None:
        self.calls = 0
        self.hold_first = asyncio.Event()

    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        self.calls += 1
        if self.calls == 1:
            yield "还在回答"
            await self.hold_first.wait()
            yield "不应送达"
            return
        yield "已切换到新一轮。"


class RepeatingAsrEngine:
    async def start_session(self):
        return RepeatingAsrSession()


class RepeatingAsrSession:
    def __init__(self) -> None:
        self.available = False
        self.revision = 0

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        del pcm16, sample_rate_hz
        if not self.available:
            self.available = True
            self.revision += 1

    async def consume_transcript(self) -> str:
        if not self.available:
            return ""
        self.available = False
        return "请切换到新问题"

    async def peek_transcript(self) -> str:
        return "请切换到新问题" if self.available else ""

    async def snapshot(self) -> AsrSnapshot:
        return AsrSnapshot(
            text="请切换到新问题" if self.available else "",
            revision=self.revision,
            sentence_end_revision=0,
        )

    async def wait_for_update(self, **kwargs):
        del kwargs
        return await self.snapshot()

    async def close(self) -> None:
        return None

    @property
    def is_alive(self) -> bool:
        return True


async def test_audio_turn_is_journaled_projected_answered_and_settled_automatically() -> None:
    journal = InMemoryConversationJournal()
    deliveries = InMemorySpeechDeliveryStore()
    turn_context = replace(context(), turn_id="turn-2", generation=2)
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("明天上海天气怎么样")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(WeatherBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoTts()),
        speech_deliveries=deliveries,
    ).open(context=context(), profile=None)
    journaled = JournaledRealtimeConversation(
        context=context(), journal=journal, engine_conversation=core
    )
    conversation = RealtimeTurnController(
        context=context(), conversation=journaled
    )
    events = conversation.events()

    await conversation.send(
        AppendAudio(
            command_id="audio-1",
            idempotency_key="audio-1",
            context=turn_context,
            frame=audio(0, 1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="audio-2",
            idempotency_key="audio-2",
            context=turn_context,
            frame=audio(1, 0),
        )
    )

    emitted = []
    while len(emitted) < 30:
        event = await anext(events)
        emitted.append(event)
        if isinstance(event, ResponseCompleted):
            break
    items = await journal.read(JournalScope.from_context(turn_context))
    assert [item.kind for item in items] == [
        ConversationItemKind.USER_INPUT,
        ConversationItemKind.ASSISTANT_OUTPUT,
    ]
    assert items[0].context.turn_id == "turn-2"
    assert items[0].context.generation == 2
    assert items[1].display is not None
    assert items[1].display.markdown == "明天上海有小雨，记得带伞。"
    assert items[1].spoken is not None
    assert items[1].spoken.text == "明天上海有小雨，记得带伞。"
    assert sum(isinstance(event, ItemProjected) for event in emitted) >= 1

    delivery = await deliveries.latest_for_item(items[1].item_id)
    assert delivery is not None
    assert delivery.intended_spoken_content == "明天上海有小雨，记得带伞。"
    assert delivery.status is SpeechDeliveryStatus.ACTIVE
    await conversation.send(
        ReportPlaybackProgress(
            command_id="playback-complete",
            idempotency_key="playback-complete",
            context=turn_context,
            speech_id=delivery.speech_id,
            delivered_text_end=len(delivery.intended_spoken_content),
            played_audio_end_us=1_200_000,
            completed=True,
        )
    )
    while not isinstance(await anext(events), SpeechPlaybackProgress):
        pass
    settled = await deliveries.get(delivery.speech_id)
    assert settled is not None
    assert settled.status is SpeechDeliveryStatus.COMPLETED

    await conversation.close()


async def test_external_speech_defaults_to_one_model_visible_assistant_item() -> None:
    journal = InMemoryConversationJournal()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
        brain=LegacyBrainCapabilityAdapter(WeatherBrain()),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoTts()),
    ).open(context=context(), profile=None)
    conversation = RealtimeTurnController(
        context=context(),
        conversation=JournaledRealtimeConversation(
            context=context(), journal=journal, engine_conversation=core
        ),
    )
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
            delta="后台任务已经完成。",
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

    while not isinstance(await anext(events), SpeechTextCommitted):
        pass
    items = await journal.read(JournalScope.from_context(context()))
    assert len(items) == 1
    assert items[0].kind is ConversationItemKind.ASSISTANT_OUTPUT
    assert items[0].spoken is not None
    assert items[0].spoken.text == "后台任务已经完成。"

    await conversation.close()


async def test_floor_claim_cancels_active_response_then_commits_new_user_turn() -> None:
    journal = InMemoryConversationJournal()
    brain = BargeInBrain()
    core = await CascadedRealtimeEngine(
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(energy_threshold=500, silence_duration_ms=32)
            )
        ),
        asr=LegacyAsrCapabilityAdapter(RepeatingAsrEngine()),
        turn_manager=LegacyTurnManagerCapabilityAdapter(
            TurnPolicy,
            dual_intent_classifier=AlwaysFloorClaimClassifier(),
        ),
        brain=LegacyBrainCapabilityAdapter(brain),
        speech_renderer=DeterministicSpeechRenderer(),
        tts=LegacyTtsCapabilityAdapter(EchoTts()),
    ).open(context=context(), profile=None)
    conversation = RealtimeTurnController(
        context=context(),
        conversation=JournaledRealtimeConversation(
            context=context(), journal=journal, engine_conversation=core
        ),
    )
    events = conversation.events()

    await conversation.send(
        AppendAudio(
            command_id="first-audio-1",
            idempotency_key="first-audio-1",
            context=context(),
            frame=audio(0, 1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="first-audio-2",
            idempotency_key="first-audio-2",
            context=context(),
            frame=audio(1, 0),
        )
    )
    first_response_id = ""
    while not first_response_id:
        event = await anext(events)
        if isinstance(event, AudioDelta):
            first_response_id = event.response_id

    second_context = replace(context(), turn_id="turn-2", generation=2)
    await conversation.send(
        AppendAudio(
            command_id="second-audio-1",
            idempotency_key="second-audio-1",
            context=second_context,
            frame=audio(2, 1_000),
        )
    )
    await conversation.send(
        AppendAudio(
            command_id="second-audio-2",
            idempotency_key="second-audio-2",
            context=second_context,
            frame=audio(3, 0),
        )
    )

    emitted = []
    while len(emitted) < 40:
        try:
            event = await asyncio.wait_for(anext(events), timeout=0.5)
        except TimeoutError as error:
            raise AssertionError(
                "barge-in stalled after "
                f"{[(type(item).__name__, getattr(item, 'error', None)) for item in emitted]}"
            ) from error
        emitted.append(event)
        if isinstance(event, ResponseCompleted) and event.response_id != first_response_id:
            break
    assert any(isinstance(event, AssistantYieldRequested) for event in emitted)
    cancelled = next(event for event in emitted if isinstance(event, ResponseCancelled))
    assert cancelled.response_id == first_response_id
    assert cancelled.reason == "barge_in_floor_claim"
    assert brain.calls == 2
    items = await journal.read(JournalScope.from_context(context()))
    assert [item.kind for item in items].count(ConversationItemKind.USER_INPUT) == 2
    assert [item.kind for item in items].count(ConversationItemKind.ASSISTANT_OUTPUT) == 2
    await conversation.close()
