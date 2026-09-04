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
    InMemoryConversationJournal,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.realtime import (
    AssistantContent,
    AudioEncoding,
    AudioFrame,
    DisplayContent,
    SpokenContent,
)
from server.realtime.capabilities import (
    AnalyzeVadAudio,
    AppendAsrAudio,
    AppendTtsText,
    AsrCommitRejected,
    AsrCommitRequested,
    AsrDiscardRequested,
    AsrEndpointHint,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
    AssistantYieldRequested,
    BrainDelegationRequested,
    BrainResponseCompleted,
    BrainResponseFailed,
    BrainResponseStarted,
    BrainTextDelta,
    CancelTts,
    CascadedCapabilityFailed,
    CascadedInputPipeline,
    CommitAsrInput,
    CommitTts,
    DeterministicSpeechRenderer,
    DialogueStateChanged,
    LegacyAsrCapabilityAdapter,
    LegacyBrainCapabilityAdapter,
    LegacyTtsCapabilityAdapter,
    LegacyTurnManagerCapabilityAdapter,
    LegacyVadCapabilityAdapter,
    ObserveAsrEvent,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveConversationItem,
    ObserveSystemResponseCompleted,
    ObserveVadEvent,
    RequestBrainResponse,
    StartTts,
    TtsAudioFrame,
    TtsCancelled,
    TtsCompleted,
    TtsTextMode,
    UserTurnCommitted,
    VadSpeechStarted,
    VadSpeechStopped,
    resolve_spoken_content,
)
from server.realtime.capabilities.brain_streaming import BrainDelegationCall
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.speech.tts import SynthesizedAudioChunk
from server.turn_policy.dual_intent import DualIntent
from server.turn_policy.eot_classifier import EotClassification, EotContext, EotDecision
from server.turn_policy.policy import TurnPolicy
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionClassification,
    InterruptionLabel,
)
from server.turn_policy.signals import Signal
from server.turn_policy.states import DialogueState


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


async def test_legacy_vad_adapter_emits_typed_activity_events_from_audio_frames() -> None:
    adapter = LegacyVadCapabilityAdapter(
        lambda: EnergyVad(
            EnergyVadConfig(
                energy_threshold=500,
                silence_duration_ms=32,
            )
        )
    )
    session = await adapter.open(context=context())
    events = session.events()

    await session.send(AnalyzeVadAudio(frame=pcm_frame(sequence=0, amplitude=1_000)))
    started = await anext(events)
    assert isinstance(started, VadSpeechStarted)
    assert started.audio_timestamp_us == 0

    await session.send(AnalyzeVadAudio(frame=pcm_frame(sequence=1, amplitude=0)))
    stopped = await anext(events)
    assert isinstance(stopped, VadSpeechStopped)
    assert stopped.audio_timestamp_us == 64_000
    assert stopped.silence_duration_us == 32_000

    await session.close()


async def test_asr_provider_text_is_only_final_after_explicit_engine_commit() -> None:
    adapter = LegacyAsrCapabilityAdapter(PreloadedAsrEngine("你好，帮我查天气"))
    session = await adapter.open(context=context())
    events = session.events()

    await session.send(AppendAsrAudio(frame=pcm_frame(sequence=0, amplitude=1_000)))
    delta = await anext(events)
    assert isinstance(delta, AsrTranscriptDelta)
    assert delta.delta == "你好，帮我查天气"
    assert delta.accumulated_text == "你好，帮我查天气"

    await session.send(CommitAsrInput(reason="turn_manager_commit"))
    final = await anext(events)
    assert isinstance(final, AsrTranscriptFinal)
    assert final.text == "你好，帮我查天气"
    assert final.reason == "turn_manager_commit"

    await session.close()


async def test_empty_asr_commit_is_a_recoverable_event_instead_of_killing_the_route() -> None:
    session = await LegacyAsrCapabilityAdapter(PreloadedAsrEngine("")).open(
        context=context()
    )
    events = session.events()

    await session.send(CommitAsrInput(reason="turn_manager_commit"))

    rejected = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(rejected, AsrCommitRejected)
    assert rejected.reason == "empty_transcript"
    await session.close()


class RestartableAsrSession:
    def __init__(
        self,
        transcript: str,
        *,
        alive: bool = True,
        die_on_first_push: bool = False,
        close_error: Exception | None = None,
    ) -> None:
        self.transcript = transcript
        self.alive = alive
        self.die_on_first_push = die_on_first_push
        self.close_error = close_error
        self.pushes: list[bytes] = []
        self.closed = False
        self._revision = 0

    @property
    def is_alive(self) -> bool:
        return self.alive

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        assert sample_rate_hz == 16_000
        self.pushes.append(pcm16)
        if self.die_on_first_push:
            self.die_on_first_push = False
            self.alive = False
            return
        self._revision = 1

    async def consume_transcript(self) -> str:
        return self.transcript if self._revision else ""

    async def peek_transcript(self) -> str:
        return self.transcript if self._revision else ""

    async def snapshot(self):
        from server.speech.asr import AsrSnapshot

        return AsrSnapshot(
            text=self.transcript if self._revision else "",
            revision=self._revision,
            sentence_end_revision=0,
            supports_sentence_end=False,
        )

    async def wait_for_update(
        self,
        *,
        after_revision: int,
        after_sentence_end_revision: int,
    ):
        del after_revision, after_sentence_end_revision
        return await self.snapshot()

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class SequencedAsrEngine:
    def __init__(self, sessions: list[RestartableAsrSession]) -> None:
        self.sessions = sessions
        self.started = 0

    async def start_session(self) -> RestartableAsrSession:
        session = self.sessions[self.started]
        self.started += 1
        return session


async def test_asr_adapter_restarts_session_that_died_while_browser_was_idle() -> None:
    expired = RestartableAsrSession("", alive=False)
    replacement = RestartableAsrSession("重新连接成功")
    engine = SequencedAsrEngine([expired, replacement])
    session = await LegacyAsrCapabilityAdapter(engine).open(context=context())
    events = session.events()
    frame = pcm_frame(sequence=0, amplitude=1_000)

    await session.send(AppendAsrAudio(frame=frame))

    delta = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(delta, AsrTranscriptDelta)
    assert delta.accumulated_text == "重新连接成功"
    assert engine.started == 2
    assert expired.closed is True
    assert replacement.pushes == [frame.data]

    await session.close()


async def test_asr_adapter_retries_frame_when_provider_dies_during_send() -> None:
    failed = RestartableAsrSession("", die_on_first_push=True)
    replacement = RestartableAsrSession("当前音频没有丢失")
    engine = SequencedAsrEngine([failed, replacement])
    session = await LegacyAsrCapabilityAdapter(engine).open(context=context())
    events = session.events()
    frame = pcm_frame(sequence=0, amplitude=1_000)

    await session.send(AppendAsrAudio(frame=frame))

    delta = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(delta, AsrTranscriptDelta)
    assert delta.accumulated_text == "当前音频没有丢失"
    assert engine.started == 2
    assert failed.pushes == [frame.data]
    assert replacement.pushes == [frame.data]

    await session.close()


async def test_asr_adapter_restart_ignores_failure_closing_expired_socket() -> None:
    expired = RestartableAsrSession(
        "",
        alive=False,
        close_error=ConnectionError("socket is already gone"),
    )
    replacement = RestartableAsrSession("关闭失败也能重连")
    engine = SequencedAsrEngine([expired, replacement])
    session = await LegacyAsrCapabilityAdapter(engine).open(context=context())
    events = session.events()

    await session.send(AppendAsrAudio(frame=pcm_frame(sequence=0, amplitude=1_000)))

    delta = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(delta, AsrTranscriptDelta)
    assert delta.accumulated_text == "关闭失败也能重连"
    assert engine.started == 2

    await session.close()


async def test_turn_manager_commits_only_after_vad_decision_and_asr_final() -> None:
    adapter = LegacyTurnManagerCapabilityAdapter(TurnPolicy)
    session = await adapter.open(context=context())
    events = session.events()
    started = VadSpeechStarted(context=context(), audio_timestamp_us=0)

    await session.send(ObserveVadEvent(event=started))
    listening = await anext(events)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.from_state is DialogueState.IDLE
    assert listening.to_state is DialogueState.LISTEN

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="你好，帮我查天气",
                accumulated_text="你好，帮我查天气",
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="你好，帮我查天气",
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=64_000,
                silence_duration_us=32_000,
            )
        )
    )

    speaking = await anext(events)
    commit_requested = await anext(events)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit_requested, AsrCommitRequested)

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=context(),
                revision=1,
                text="你好，帮我查天气",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await anext(events)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "你好，帮我查天气"
    assert committed.provider_endpoint_observed is True
    assert committed.committed_at >= datetime.now(UTC).replace(microsecond=0)

    await session.send(
        ObserveSystemResponseCompleted(response_id="response-1")
    )
    idle = await anext(events)
    assert isinstance(idle, DialogueStateChanged)
    assert idle.from_state is DialogueState.SPEAK
    assert idle.to_state is DialogueState.IDLE

    await session.close()


async def test_turn_manager_treats_asr_revisions_during_commit_wait_as_the_same_turn() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(TurnPolicy).open(
        context=context()
    )
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    assert isinstance(await anext(events), DialogueStateChanged)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="今天天气怎么样",
                accumulated_text="今天天气怎么样",
                audio_timestamp_us=320_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=576_000,
                silence_duration_us=256_000,
            )
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.1), DialogueStateChanged)
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.1), AsrCommitRequested)

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=2,
                delta="？",
                accumulated_text="今天天气怎么样？",
                audio_timestamp_us=576_000,
            )
        )
    )
    pending = asyncio.create_task(anext(events))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(pending), timeout=0.005)

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=context(),
                revision=2,
                text="今天天气怎么样？",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(pending, timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "今天天气怎么样？"

    await session.close()


async def test_turn_manager_recovers_after_empty_commit_and_accepts_late_asr() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(TurnPolicy).open(
        context=context()
    )
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    assert isinstance(await anext(events), DialogueStateChanged)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="嗯",
                accumulated_text="嗯",
                audio_timestamp_us=320_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=576_000,
                silence_duration_us=256_000,
            )
        )
    )
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.1), DialogueStateChanged)
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.1), AsrCommitRequested)

    await session.send(
        ObserveAsrEvent(
            event=AsrCommitRejected(
                context=context(),
                reason="empty_transcript",
            )
        )
    )
    recovered = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(recovered, DialogueStateChanged)
    assert recovered.from_state is DialogueState.SPEAK
    assert recovered.to_state is DialogueState.IDLE

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=2,
                delta="北京天气怎么样",
                accumulated_text="北京天气怎么样",
                audio_timestamp_us=608_000,
            )
        )
    )
    listening = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.from_state is DialogueState.IDLE
    assert listening.to_state is DialogueState.LISTEN

    await session.close()


async def test_late_asr_text_recovers_after_empty_vad_stop_returns_idle() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(TurnPolicy).open(
        context=context()
    )
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    assert isinstance(await anext(events), DialogueStateChanged)
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )

    idle = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(idle, DialogueStateChanged)
    assert idle.from_state is DialogueState.LISTEN
    assert idle.to_state is DialogueState.IDLE

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="让我",
                accumulated_text="让我",
                audio_timestamp_us=288_000,
            )
        )
    )
    listening = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.from_state is DialogueState.IDLE
    assert listening.to_state is DialogueState.LISTEN
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=2,
                delta="查一下天气",
                accumulated_text="让我查一下天气",
                audio_timestamp_us=320_000,
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=2,
                text="让我查一下天气",
            )
        )
    )

    speaking = await asyncio.wait_for(anext(events), timeout=0.1)
    commit_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit_requested, AsrCommitRequested)

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=context(),
                revision=2,
                text="让我查一下天气",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "让我查一下天气"
    assert committed.provider_endpoint_observed is True

    await session.close()


async def test_short_greeting_recovers_when_asr_arrives_after_legacy_window() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(TurnPolicy).open(
        context=context()
    )
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    await anext(events)
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )
    await anext(events)

    # The real provider trace delivered the first useful ASR revision about
    # 1.14s after the empty VAD stop. It must still recover the same turn.
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="你好呀",
                accumulated_text="你好呀",
                audio_timestamp_us=1_400_000,
            )
        )
    )
    listening = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.to_state is DialogueState.LISTEN

    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="你好呀",
            )
        )
    )
    speaking = await asyncio.wait_for(anext(events), timeout=0.1)
    commit_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit_requested, AsrCommitRequested)

    await session.close()


async def test_stale_asr_text_after_empty_vad_stop_does_not_create_a_turn() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        late_asr_recovery_ms=2000,
    ).open(context=context())
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    assert isinstance(await anext(events), DialogueStateChanged)
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )
    idle = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(idle, DialogueStateChanged)
    assert idle.to_state is DialogueState.IDLE

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="环境误识别",
                accumulated_text="环境误识别",
                audio_timestamp_us=2_800_000,
            )
        )
    )

    discarded = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(discarded, AsrDiscardRequested)
    assert discarded.reason == "late_asr_after_aborted_vad"
    await session.close()


async def test_new_asr_phrase_can_recover_after_discarded_stale_endpoint() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        late_asr_recovery_ms=2000,
    ).open(context=context())
    events = session.events()
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    await anext(events)
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )
    await anext(events)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="环境误识别",
                accumulated_text="环境误识别",
                audio_timestamp_us=2_800_000,
            )
        )
    )
    discarded = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(discarded, AsrDiscardRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="环境误识别",
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=2,
                delta="你好",
                accumulated_text="你好",
                audio_timestamp_us=1_100_000,
            )
        )
    )

    listening = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.to_state is DialogueState.LISTEN
    await session.close()


async def test_turn_manager_returns_idle_when_vad_stops_without_asr_text() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(TurnPolicy).open(
        context=context()
    )
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    listening = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.to_state is DialogueState.LISTEN

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )

    idle = await asyncio.wait_for(anext(events), timeout=0.05)
    assert isinstance(idle, DialogueStateChanged)
    assert idle.from_state is DialogueState.LISTEN
    assert idle.to_state is DialogueState.IDLE

    await session.close()


async def test_turn_manager_uses_stable_asr_idle_when_acoustic_vad_never_stops() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        asr_idle_stop_ms=10,
    ).open(context=context())
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=0)
        )
    )
    assert isinstance(await anext(events), DialogueStateChanged)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="今天天气怎么样",
                accumulated_text="今天天气怎么样",
                audio_timestamp_us=320_000,
            )
        )
    )

    pending_event = asyncio.create_task(anext(events))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(pending_event), timeout=0.005)

    speaking = await asyncio.wait_for(pending_event, timeout=0.1)
    commit_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit_requested, AsrCommitRequested)
    assert commit_requested.audio_end_timestamp_us == 320_000

    await session.close()


async def test_turn_manager_commits_asr_input_when_vad_misses_speech_onset() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        asr_idle_stop_ms=10,
    ).open(context=context())
    events = session.events()

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="给我讲个故事",
                accumulated_text="给我讲个故事",
                audio_timestamp_us=320_000,
            )
        )
    )

    listening = await asyncio.wait_for(anext(events), timeout=0.05)
    speaking = await asyncio.wait_for(anext(events), timeout=0.1)
    commit_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(listening, DialogueStateChanged)
    assert listening.from_state is DialogueState.IDLE
    assert listening.to_state is DialogueState.LISTEN
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit_requested, AsrCommitRequested)

    await session.close()


class IncompleteEotClassifier:
    async def classify(self, *, text: str, generation: int) -> EotClassification:
        assert text == "我想查一下"
        assert generation == 1
        return EotClassification(
            decision=EotDecision.INCOMPLETE,
            confidence=0.98,
            source="test",
        )


class ContextRecordingEotClassifier:
    def __init__(self) -> None:
        self.called = asyncio.Event()
        self.context: EotContext | None = None

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        raise AssertionError("contextual classifier path should be used")

    async def classify_with_context(
        self,
        *,
        text: str,
        generation: int,
        context: EotContext,
    ) -> EotClassification:
        assert text == "北京"
        assert generation == 1
        self.context = context
        self.called.set()
        return EotClassification(EotDecision.COMPLETE, source="test")


async def test_turn_manager_uses_projected_committed_dialogue_as_eot_history() -> None:
    classifier = ContextRecordingEotClassifier()
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        eot_classifier=classifier,
    ).open(context=context())
    journal = InMemoryConversationJournal()
    user = await journal.append(
        ConversationItemDraft(
            item_id="user-history",
            context=context(),
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("我想订明天的票"),),
        )
    )
    assistant = await journal.append(
        ConversationItemDraft(
            item_id="assistant-history",
            context=context(),
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("你想去哪里？"),),
        )
    )

    await session.send(ObserveConversationItem(item=user.item))
    await session.send(ObserveConversationItem(item=assistant.item))
    await session.send(ObserveConversationItem(item=assistant.item))
    await session.send(
        ObserveConversationItem(
            item=replace(
                assistant.item,
                content=(TextContent("你想去哪"),),
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="北京",
            )
        )
    )
    await asyncio.wait_for(classifier.called.wait(), timeout=0.1)

    assert classifier.context is not None
    assert [(item.role, item.content) for item in classifier.context.history] == [
        ("user", "我想订明天的票"),
        ("assistant", "你想去哪"),
    ]
    await session.close()


class RecordingResponsePrefetcher:
    def __init__(self) -> None:
        self.prepared: list[TurnContent] = []
        self.invalidated: list[tuple[int, str]] = []

    async def prepare(self, turn: TurnContent) -> bool:
        self.prepared.append(turn)
        return True

    async def invalidate(self, generation: int, *, reason: str) -> bool:
        self.invalidated.append((generation, reason))
        return True


async def test_turn_manager_prefetches_endpoint_candidate_and_invalidates_revision() -> None:
    prefetcher = RecordingResponsePrefetcher()
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        response_prefetcher=prefetcher,
    ).open(context=context())

    await session.send(
        ObserveVadEvent(event=VadSpeechStarted(context=context(), audio_timestamp_us=0))
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="帮我查天气",
                accumulated_text="帮我查天气",
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="帮我查天气",
            )
        )
    )

    assert prefetcher.prepared == [TurnContent(text="帮我查天气", generation=1)]
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=2,
                delta="，明天的",
                accumulated_text="帮我查天气，明天的",
            )
        )
    )
    assert prefetcher.invalidated == [(1, "asr_increment")]

    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=2,
                text="帮我查天气，明天的",
            )
        )
    )
    assert prefetcher.prepared == [
        TurnContent(text="帮我查天气", generation=1),
        TurnContent(text="帮我查天气，明天的", generation=1),
    ]

    await session.close()


async def test_turn_manager_holds_incomplete_semantic_endpoint_until_timeout() -> None:
    session = await LegacyTurnManagerCapabilityAdapter(
        TurnPolicy,
        eot_classifier=IncompleteEotClassifier(),
        incomplete_timeout_ms=30,
    ).open(context=context())
    events = session.events()

    await session.send(
        ObserveVadEvent(event=VadSpeechStarted(context=context(), audio_timestamp_us=0))
    )
    await anext(events)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="我想查一下",
                accumulated_text="我想查一下",
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrEndpointHint(
                context=context(),
                revision=1,
                text="我想查一下",
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=256_000,
                silence_duration_us=256_000,
            )
        )
    )

    next_event = asyncio.create_task(anext(events))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(next_event), timeout=0.01)
    speaking = await asyncio.wait_for(next_event, timeout=0.1)
    commit = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(speaking, DialogueStateChanged)
    assert speaking.to_state is DialogueState.SPEAK
    assert isinstance(commit, AsrCommitRequested)

    await session.close()


class FloorClaimClassifier:
    async def classify(self, *, generation: int, overlap_ms: float, text: str):
        assert generation == 2
        assert overlap_ms == 900
        assert text == "等等，我补充一下"
        return DualIntent.FLOOR_CLAIM


class BackchannelClassifier:
    async def classify(self, *, generation: int, overlap_ms: float, text: str):
        del generation, overlap_ms, text
        return DualIntent.BACKCHANNEL


class SlotFillInterruptionClassifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        self.calls.append(
            {
                "assistant_text": assistant_text,
                "transcript": transcript,
                "boundary": boundary,
                "generation": generation,
            }
        )
        return InterruptionClassification(InterruptionLabel.INTERRUPT, 0.98)


class MisclassifyingBackchannelInterruptionClassifier:
    """Reproduce a conservative model suppressing a real user question."""

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del assistant_text, transcript, boundary, generation
        return InterruptionClassification(InterruptionLabel.BACKCHANNEL, 0.99)


class ProgressiveInterruptionClassifier:
    """The final revision turns an initial stop command into a new request."""

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del assistant_text, boundary, generation
        label = (
            InterruptionLabel.INTERRUPT
            if "天气" in transcript
            else InterruptionLabel.STOP
        )
        return InterruptionClassification(label, 0.99)


class InterruptedUtteranceEotClassifier:
    """Keep an admitted barge-in open until the user's sentence is complete."""

    def __init__(self) -> None:
        self.classified = asyncio.Event()
        self.reclassified = asyncio.Event()
        self.calls: list[str] = []

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        assert generation == 2
        self.calls.append(text)
        self.classified.set()
        if len(self.calls) >= 2:
            self.reclassified.set()
        if text == "你把那手机给":
            return EotClassification(
                EotDecision.INCOMPLETE,
                confidence=0.99,
                source="test",
            )
        assert text == "你把那手机给我"
        return EotClassification(
            EotDecision.COMPLETE,
            confidence=0.99,
            source="test",
        )


async def test_admitted_barge_in_still_waits_for_semantic_endpoint() -> None:
    """An interruption may stop playback without prematurely closing its turn."""

    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    eot_classifier = InterruptedUtteranceEotClassifier()
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=SlotFillInterruptionClassifier(),
        eot_classifier=eot_classifier,
        incomplete_timeout_ms=50,
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="你把那手机给",
                accumulated_text="你把那手机给",
                audio_timestamp_us=300_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=400_000,
                silence_duration_us=256_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.LISTEN
    assert isinstance(await anext(events), AssistantYieldRequested)

    await session.send(ObserveAssistantYielded(context=overlap_context))
    await asyncio.wait_for(eot_classifier.classified.wait(), timeout=0.1)
    pending_event = asyncio.create_task(anext(events))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(pending_event), timeout=0.005)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=410_000,
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=2,
                delta="你把那手机给",
                accumulated_text="你把那手机给",
                audio_timestamp_us=500_000,
                replaces_previous=True,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=600_000,
                silence_duration_us=256_000,
            )
        )
    )
    await asyncio.wait_for(eot_classifier.reclassified.wait(), timeout=0.1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(pending_event), timeout=0.005)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=610_000,
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=3,
                delta="我",
                accumulated_text="你把那手机给我",
                audio_timestamp_us=700_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=800_000,
                silence_duration_us=256_000,
            )
        )
    )

    responding = await asyncio.wait_for(pending_event, timeout=0.1)
    commit = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(responding, DialogueStateChanged)
    assert responding.to_state is DialogueState.SPEAK
    assert isinstance(commit, AsrCommitRequested)
    await session.close()


async def test_slot_fill_during_assistant_playback_yields_and_commits_a_new_turn() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    classifier = SlotFillInterruptionClassifier()
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=classifier,
    ).open(context=context())
    events = session.events()
    assistant_context = context()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)
    await session.send(
        ObserveAssistantSpokenText(
            context=assistant_context,
            text="请问您想查询哪个城市的天气？",
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="北京的",
                accumulated_text="北京的",
                audio_timestamp_us=200_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=400_000,
                silence_duration_us=256_000,
            )
        )
    )

    floor_claim = await asyncio.wait_for(anext(events), timeout=0.1)
    yield_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(floor_claim, DialogueStateChanged)
    assert floor_claim.to_state is DialogueState.LISTEN
    assert isinstance(yield_requested, AssistantYieldRequested)
    assert classifier.calls[-1] == {
        "assistant_text": "请问您想查询哪个城市的天气？",
        "transcript": "北京的",
        "boundary": InterruptionBoundary.SENTENCE_END,
        "generation": 2,
    }

    await session.send(ObserveAssistantYielded(context=overlap_context))
    assert (await anext(events)).to_state is DialogueState.SPEAK
    assert isinstance(await anext(events), AsrCommitRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=overlap_context,
                revision=1,
                text="北京的",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "北京的"
    await session.close()


async def test_model_backchannel_verdict_cannot_discard_a_non_rule_user_question() -> None:
    """A model false negative may delay barge-in, but must not lose the turn."""

    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=MisclassifyingBackchannelInterruptionClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="你好，你还能听到我吗",
                accumulated_text="你好，你还能听到我吗",
                audio_timestamp_us=700_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=900_000,
                silence_duration_us=256_000,
            )
        )
    )

    floor_claim = await asyncio.wait_for(anext(events), timeout=0.1)
    yield_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(floor_claim, DialogueStateChanged)
    assert floor_claim.to_state is DialogueState.LISTEN
    assert isinstance(yield_requested, AssistantYieldRequested)

    await session.send(ObserveAssistantYielded(context=overlap_context))
    assert (await anext(events)).to_state is DialogueState.SPEAK
    assert isinstance(await anext(events), AsrCommitRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=overlap_context,
                revision=1,
                text="你好，你还能听到我吗",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "你好，你还能听到我吗"
    await session.close()


async def test_final_revision_can_promote_an_early_stop_into_a_user_turn() -> None:
    """Stopping playback early must not freeze turn admission on a partial."""

    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=ProgressiveInterruptionClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="别说了",
                accumulated_text="别说了",
                audio_timestamp_us=250_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.LISTEN
    assert isinstance(await anext(events), AssistantYieldRequested)
    await session.send(ObserveAssistantYielded(context=overlap_context))

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=2,
                delta="，告诉我北京天气",
                accumulated_text="别说了，告诉我北京天气",
                audio_timestamp_us=700_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=900_000,
                silence_duration_us=256_000,
            )
        )
    )

    assert (await anext(events)).to_state is DialogueState.SPEAK
    assert isinstance(await anext(events), AsrCommitRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=overlap_context,
                revision=2,
                text="别说了，告诉我北京天气",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "别说了，告诉我北京天气"
    await session.close()


async def test_asr_slot_fill_recovers_when_vad_misses_onset_during_playback() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    classifier = SlotFillInterruptionClassifier()
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=classifier,
        asr_idle_stop_ms=5,
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)
    await session.send(
        ObserveAssistantSpokenText(
            context=context(),
            text="请问您想查询哪个城市的天气？",
        )
    )

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="北京的",
                accumulated_text="北京的",
                audio_timestamp_us=200_000,
            )
        )
    )

    dual = await asyncio.wait_for(anext(events), timeout=0.1)
    floor_claim = await asyncio.wait_for(anext(events), timeout=0.1)
    yield_requested = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(dual, DialogueStateChanged)
    assert dual.to_state is DialogueState.DUAL
    assert isinstance(floor_claim, DialogueStateChanged)
    assert floor_claim.to_state is DialogueState.LISTEN
    assert isinstance(yield_requested, AssistantYieldRequested)

    await session.send(ObserveAssistantYielded(context=overlap_context))
    assert (await anext(events)).to_state is DialogueState.SPEAK
    assert isinstance(await anext(events), AsrCommitRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=overlap_context,
                revision=1,
                text="北京的",
                reason="turn_manager_commit",
            )
        )
    )
    committed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(committed, UserTurnCommitted)
    assert committed.text == "北京的"
    await session.close()


async def test_turn_manager_waits_for_yield_ack_before_committing_floor_claim() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        dual_intent_classifier=FloorClaimClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    dual = await anext(events)
    assert isinstance(dual, DialogueStateChanged)
    assert dual.to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="等等，我补充一下",
                accumulated_text="等等，我补充一下",
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=1_000_000,
                silence_duration_us=256_000,
            )
        )
    )
    floor_claim = await anext(events)
    yield_requested = await anext(events)
    assert isinstance(floor_claim, DialogueStateChanged)
    assert floor_claim.to_state is DialogueState.LISTEN
    assert isinstance(yield_requested, AssistantYieldRequested)

    await session.send(ObserveAssistantYielded(context=overlap_context))
    responding = await anext(events)
    commit = await anext(events)
    assert isinstance(responding, DialogueStateChanged)
    assert responding.to_state is DialogueState.SPEAK
    assert isinstance(commit, AsrCommitRequested)
    await session.close()


async def test_semantic_floor_claim_requests_yield_before_vad_stop() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        dual_intent_classifier=FloorClaimClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    await anext(events)

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="等等，我补充一下",
                accumulated_text="等等，我补充一下",
                audio_timestamp_us=1_000_000,
            )
        )
    )

    floor_claim = await anext(events)
    yield_requested = await anext(events)
    assert isinstance(floor_claim, DialogueStateChanged)
    assert floor_claim.to_state is DialogueState.LISTEN
    assert isinstance(yield_requested, AssistantYieldRequested)
    await session.close()


async def test_turn_manager_returns_to_speaking_without_yield_for_backchannel() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        dual_intent_classifier=BackchannelClassifier(),
    ).open(context=context())
    events = session.events()

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=100_000)
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=300_000,
                silence_duration_us=256_000,
            )
        )
    )
    continued = await anext(events)
    assert isinstance(continued, DialogueStateChanged)
    assert continued.to_state is DialogueState.SPEAK

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(events), timeout=0.01)
    await session.close()


async def test_backchannel_transcript_is_discarded_before_the_next_user_turn() -> None:
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        dual_intent_classifier=BackchannelClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="嗯",
                accumulated_text="嗯",
                audio_timestamp_us=150_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=300_000,
                silence_duration_us=256_000,
            )
        )
    )

    assert (await anext(events)).to_state is DialogueState.SPEAK
    discarded = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(discarded, AsrDiscardRequested)
    assert discarded.reason == "semantic_backchannel"
    await session.close()


async def test_turn_manager_does_not_turn_assistant_playback_echo_into_a_user_turn() -> None:
    """The assistant's own spoken text is acoustic echo, not a floor claim."""

    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
    ).open(context=context())
    events = session.events()
    journal = InMemoryConversationJournal()
    assistant = await journal.append(
        ConversationItemDraft(
            item_id="assistant-echo-source",
            context=context(),
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("你好！有什么我可以帮你的吗？"),),
        )
    )
    await session.send(ObserveConversationItem(item=assistant.item))

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(context=context(), audio_timestamp_us=100_000)
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL

    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=context(),
                revision=1,
                delta="有什么我可以帮你的吗",
                accumulated_text="有什么我可以帮你的吗",
                audio_timestamp_us=1_000_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=context(),
                audio_timestamp_us=1_100_000,
                silence_duration_us=256_000,
            )
        )
    )

    continued = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(continued, DialogueStateChanged)
    assert continued.to_state is DialogueState.SPEAK
    discarded = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(discarded, AsrDiscardRequested)
    await session.close()


async def test_turn_manager_rechecks_late_final_before_committing_playback_echo() -> None:
    """A short false floor claim must be revoked by the authoritative ASR final."""

    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    session = await LegacyTurnManagerCapabilityAdapter(
        lambda: policy,
        semantic_interruption_classifier=SlotFillInterruptionClassifier(),
    ).open(context=context())
    events = session.events()
    overlap_context = replace(context(), turn_id="turn-2", generation=2)
    await session.send(
        ObserveAssistantSpokenText(
            context=context(),
            text="你好呀！有什么我可以帮你的吗？",
        )
    )

    await session.send(
        ObserveVadEvent(
            event=VadSpeechStarted(
                context=overlap_context,
                audio_timestamp_us=100_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.DUAL
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=1,
                delta="有什么",
                accumulated_text="有什么",
                audio_timestamp_us=300_000,
            )
        )
    )
    await session.send(
        ObserveVadEvent(
            event=VadSpeechStopped(
                context=overlap_context,
                audio_timestamp_us=600_000,
                silence_duration_us=256_000,
            )
        )
    )
    assert (await anext(events)).to_state is DialogueState.LISTEN
    assert isinstance(await anext(events), AssistantYieldRequested)

    await session.send(ObserveAssistantYielded(context=overlap_context))
    assert (await anext(events)).to_state is DialogueState.SPEAK
    assert isinstance(await anext(events), AsrCommitRequested)
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptDelta(
                context=overlap_context,
                revision=2,
                delta="我可以帮你",
                accumulated_text="有什么我可以帮你",
                audio_timestamp_us=900_000,
            )
        )
    )
    await session.send(
        ObserveAsrEvent(
            event=AsrTranscriptFinal(
                context=overlap_context,
                revision=2,
                text="有什么我可以帮你",
                reason="turn_manager_commit",
            )
        )
    )

    restored = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(restored, DialogueStateChanged)
    assert restored.to_state is DialogueState.IDLE
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(events), timeout=0.01)
    await session.close()


async def test_cascaded_input_pipeline_routes_audio_to_one_committed_user_turn() -> None:
    pipeline = await CascadedInputPipeline.open(
        context=context(),
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(
                    energy_threshold=500,
                    silence_duration_ms=32,
                )
            )
        ),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("你好，帮我查天气")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
    )
    events = pipeline.events()

    await pipeline.append_audio(pcm_frame(sequence=0, amplitude=1_000))
    await pipeline.append_audio(pcm_frame(sequence=1, amplitude=0))

    emitted = []
    while not any(isinstance(event, UserTurnCommitted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    partial = next(event for event in emitted if isinstance(event, AsrTranscriptDelta))
    assert partial.accumulated_text == "你好，帮我查天气"
    states = [event for event in emitted if isinstance(event, DialogueStateChanged)]
    assert states[0].to_state is DialogueState.LISTEN
    assert states[-1].to_state is DialogueState.SPEAK
    assert any(isinstance(event, AsrCommitRequested) for event in emitted)
    committed = next(event for event in emitted if isinstance(event, UserTurnCommitted))
    assert committed.text == "你好，帮我查天气"

    await pipeline.close()


async def test_cascaded_input_pipeline_hides_assistant_echo_from_public_transcript() -> None:
    pipeline = await CascadedInputPipeline.open(
        context=context(),
        vad=LegacyVadCapabilityAdapter(
            lambda: EnergyVad(
                EnergyVadConfig(
                    energy_threshold=500,
                    silence_duration_ms=32,
                )
            )
        ),
        asr=LegacyAsrCapabilityAdapter(
            PreloadedAsrEngine("有什么我可以帮你的吗")
        ),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
    )
    events = pipeline.events()
    await pipeline.response_started("response-1", context=context())
    await pipeline.assistant_spoken_text(
        "你好！有什么我可以帮你的吗？",
        context=context(),
    )
    await pipeline.append_audio(pcm_frame(sequence=0, amplitude=1_000))
    await asyncio.sleep(0.01)
    await pipeline.append_audio(pcm_frame(sequence=1, amplitude=0))

    emitted = []
    while not any(isinstance(event, AsrDiscardRequested) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert not any(isinstance(event, AsrTranscriptDelta) for event in emitted)
    assert not any(isinstance(event, UserTurnCommitted) for event in emitted)
    await pipeline.close()


class EchoDuplexTts:
    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async for text in text_stream:
            yield SynthesizedAudioChunk(
                pcm16=text.encode(),
                sample_rate_hz=24_000,
                is_final=False,
            )
        yield SynthesizedAudioChunk(
            pcm16=b"",
            sample_rate_hz=24_000,
            is_final=True,
        )


class EchoCommitOnlyTts:
    async def synthesize_stream(
        self,
        text: str,
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        yield SynthesizedAudioChunk(
            pcm16=text.encode(),
            sample_rate_hz=24_000,
            is_final=True,
        )


class WarmableEchoDuplexTts(EchoDuplexTts):
    def __init__(self) -> None:
        self.warm_started = asyncio.Event()
        self.release_warmup = asyncio.Event()
        self.synthesis_started = asyncio.Event()

    async def warmup(self) -> None:
        self.warm_started.set()
        await self.release_warmup.wait()

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        self.synthesis_started.set()
        async for chunk in super().synthesize_duplex(text_stream):
            yield chunk


async def test_tts_capability_warms_provider_on_open_before_first_synthesis() -> None:
    engine = WarmableEchoDuplexTts()
    session = await LegacyTtsCapabilityAdapter(engine).open(context=context())
    await asyncio.wait_for(engine.warm_started.wait(), timeout=0.05)

    await session.send(StartTts(speech_id="speech-1"))
    await session.send(
        AppendTtsText(speech_id="speech-1", text_sequence=1, delta="你好")
    )
    await asyncio.sleep(0)
    assert not engine.synthesis_started.is_set()

    engine.release_warmup.set()
    await asyncio.wait_for(engine.synthesis_started.wait(), timeout=0.05)
    await session.close()


async def test_tts_capability_streams_audio_before_text_commit() -> None:
    adapter = LegacyTtsCapabilityAdapter(EchoDuplexTts())
    session = await adapter.open(context=context())
    events = session.events()
    await session.send(StartTts(speech_id="speech-1"))

    await session.send(
        AppendTtsText(
            speech_id="speech-1",
            text_sequence=1,
            delta="正在查询",
        )
    )

    audio = await anext(events)
    assert isinstance(audio, TtsAudioFrame)
    assert audio.speech_id == "speech-1"
    assert audio.frame.data == "正在查询".encode()

    await session.send(CommitTts(speech_id="speech-1"))
    completed = await anext(events)
    assert isinstance(completed, TtsCompleted)
    assert completed.speech_id == "speech-1"

    await session.close()


async def test_tts_capability_accepts_a_new_speech_after_completion() -> None:
    session = await LegacyTtsCapabilityAdapter(EchoDuplexTts()).open(context=context())
    events = session.events()
    for speech_id, text in (("speech-1", "第一轮"), ("speech-2", "第二轮")):
        await session.send(StartTts(speech_id=speech_id))
        await session.send(
            AppendTtsText(
                speech_id=speech_id,
                text_sequence=1,
                delta=text,
            )
        )
        assert isinstance(await anext(events), TtsAudioFrame)
        await session.send(CommitTts(speech_id=speech_id))
        assert isinstance(await anext(events), TtsCompleted)

    await session.close()


async def test_session_scoped_tts_uses_each_speech_current_turn_context() -> None:
    session = await LegacyTtsCapabilityAdapter(EchoDuplexTts()).open(context=context())
    events = session.events()
    second_turn = replace(context(), turn_id="turn-2", generation=2)
    await session.send(StartTts(speech_id="speech-2", context=second_turn))
    await session.send(
        AppendTtsText(speech_id="speech-2", text_sequence=1, delta="第二轮")
    )

    audio = await anext(events)
    assert isinstance(audio, TtsAudioFrame)
    assert audio.context.turn_id == "turn-2"
    assert audio.context.generation == 2
    await session.send(CommitTts(speech_id="speech-2"))
    assert isinstance(await anext(events), TtsCompleted)
    await session.close()


async def test_tts_capability_cancellation_stops_active_duplex_synthesis() -> None:
    session = await LegacyTtsCapabilityAdapter(EchoDuplexTts()).open(context=context())
    events = session.events()
    await session.send(StartTts(speech_id="speech-1"))
    await session.send(
        AppendTtsText(
            speech_id="speech-1",
            text_sequence=1,
            delta="这部分已经开始合成",
        )
    )
    assert isinstance(await anext(events), TtsAudioFrame)

    await session.send(CancelTts(speech_id="speech-1", reason="barge_in"))
    cancelled = await anext(events)
    assert isinstance(cancelled, TtsCancelled)
    assert cancelled.reason == "barge_in"

    await session.close()


async def test_non_duplex_tts_declares_commit_only_and_synthesizes_after_commit() -> None:
    session = await LegacyTtsCapabilityAdapter(EchoCommitOnlyTts()).open(context=context())
    events = session.events()
    assert session.text_mode is TtsTextMode.COMMIT_ONLY
    await session.send(StartTts(speech_id="speech-1"))
    await session.send(
        AppendTtsText(
            speech_id="speech-1",
            text_sequence=1,
            delta="提交以后再合成",
        )
    )

    await session.send(CommitTts(speech_id="speech-1"))

    audio = await anext(events)
    completed = await anext(events)
    assert isinstance(audio, TtsAudioFrame)
    assert audio.frame.data == "提交以后再合成".encode()
    assert isinstance(completed, TtsCompleted)

    await session.close()


async def test_explicit_spoken_content_bypasses_speech_renderer() -> None:
    content = AssistantContent(
        semantic=(TextContent("完整语义内容，包含详细数据和来源。"),),
        display=DisplayContent("## 完整结果\n\n- 详细数据\n- [来源](https://example.com)"),
        spoken=SpokenContent("简短播报内容。"),
    )

    spoken = await resolve_spoken_content(
        content,
        renderer=DeterministicSpeechRenderer(),
    )

    assert spoken.text == "简短播报内容。"


async def test_default_speech_renderer_removes_formatting_without_changing_facts() -> None:
    content = AssistantContent(
        semantic=(TextContent("上海明天晴，最高温度 24℃。"),),
        display=DisplayContent(
            "## 上海天气\n\n- **天气**：晴\n- **最高温度**：24℃\n- [查看来源](https://example.com)"
        ),
    )

    spoken = await resolve_spoken_content(
        content,
        renderer=DeterministicSpeechRenderer(),
    )

    assert spoken.text == "上海天气 天气：晴 最高温度：24℃ 查看来源"


class GatedBrain:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream(self, content: TurnContent) -> AsyncIterator[str]:
        assert content.text == "你好"
        yield "第一段"
        await self.release.wait()
        yield "第二段"


class DelegatingBrain:
    async def stream(self, content: TurnContent):
        assert content.text == "后台检查项目"
        yield BrainDelegationCall(
            delegation_request_id="delegation-1",
            instruction="Inspect the project without modifying files",
            agent_name="codex",
        )


async def test_brain_capability_emits_typed_delegation_proposal() -> None:
    session = await LegacyBrainCapabilityAdapter(DelegatingBrain()).open(
        context=context()
    )
    events = session.events()
    await session.send(
        RequestBrainResponse(
            response_id="response-delegation",
            turn=TurnContent(text="后台检查项目", generation=1),
        )
    )

    assert isinstance(await anext(events), BrainResponseStarted)
    proposed = await anext(events)
    assert isinstance(proposed, BrainDelegationRequested)
    assert proposed.delegation_request_id == "delegation-1"
    assert proposed.instruction == "Inspect the project without modifying files"
    assert proposed.agent_name == "codex"
    assert isinstance(await anext(events), BrainResponseCompleted)
    await session.close()


async def test_brain_capability_preserves_streaming_response_events() -> None:
    brain = GatedBrain()
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    events = session.events()

    await session.send(
        RequestBrainResponse(
            response_id="response-1",
            turn=TurnContent(text="你好", generation=1),
        )
    )

    assert isinstance(await anext(events), BrainResponseStarted)
    first = await anext(events)
    assert isinstance(first, BrainTextDelta)
    assert first.delta == "第一段"

    brain.release.set()
    second = await anext(events)
    completed = await anext(events)
    assert isinstance(second, BrainTextDelta)
    assert second.delta == "第二段"
    assert isinstance(completed, BrainResponseCompleted)

    await session.close()


class AckThenEmptyAssertionBrain:
    async def stream(self, content: TurnContent) -> AsyncIterator[str]:
        del content
        yield "我查一下，马上告诉你。"
        raise AssertionError


async def test_brain_capability_turns_empty_provider_error_into_terminal_failure() -> None:
    session = await LegacyBrainCapabilityAdapter(AckThenEmptyAssertionBrain()).open(
        context=context()
    )
    events = session.events()

    await session.send(
        RequestBrainResponse(
            response_id="response-provider-error",
            turn=TurnContent(text="明天天气怎么样？", generation=1),
        )
    )

    assert isinstance(await anext(events), BrainResponseStarted)
    acknowledgement = await anext(events)
    assert isinstance(acknowledgement, BrainTextDelta)
    assert acknowledgement.delta == "我查一下，马上告诉你。"
    failed = await asyncio.wait_for(anext(events), timeout=0.1)
    assert isinstance(failed, BrainResponseFailed)
    assert failed.error == "AssertionError"

    await session.close()


async def test_session_scoped_brain_uses_each_request_current_turn_context() -> None:
    brain = GatedBrain()
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    events = session.events()
    second_turn = replace(context(), turn_id="turn-2", generation=2)

    await session.send(
        RequestBrainResponse(
            response_id="response-2",
            turn=TurnContent(text="你好", generation=2),
            context=second_turn,
        )
    )

    started = await anext(events)
    assert isinstance(started, BrainResponseStarted)
    assert started.context.turn_id == "turn-2"
    assert started.context.generation == 2
    brain.release.set()
    while not isinstance(await anext(events), BrainResponseCompleted):
        pass
    await session.close()


class FailingVadSession:
    async def send(self, command: AnalyzeVadAudio) -> None:
        del command

    async def events(self):
        await asyncio.sleep(0)
        raise RuntimeError("VAD provider disconnected")
        if False:
            yield

    async def close(self) -> None:
        return None


class FailingVadProvider:
    async def open(self, *, context: InteractionContext) -> FailingVadSession:
        del context
        return FailingVadSession()


class TrackedCapabilitySession:
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


class TrackedCapabilityProvider:
    def __init__(self) -> None:
        self.session = TrackedCapabilitySession()

    async def open(self, *, context: InteractionContext):
        del context
        return self.session


class OpenFailureProvider:
    async def open(self, *, context: InteractionContext):
        del context
        raise RuntimeError("ASR credentials rejected")


async def test_partial_input_pipeline_open_closes_successful_capability_sessions() -> None:
    vad = TrackedCapabilityProvider()
    turn_manager = TrackedCapabilityProvider()

    with pytest.raises(RuntimeError, match="ASR credentials rejected"):
        await CascadedInputPipeline.open(
            context=context(),
            vad=vad,
            asr=OpenFailureProvider(),
            turn_manager=turn_manager,
        )

    assert vad.session.closed is True
    assert turn_manager.session.closed is True


async def test_cascaded_pipeline_exposes_capability_pump_failure() -> None:
    pipeline = await CascadedInputPipeline.open(
        context=context(),
        vad=FailingVadProvider(),
        asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("测试")),
        turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
    )
    events = pipeline.events()

    failed = await anext(events)
    assert isinstance(failed, CascadedCapabilityFailed)
    assert failed.capability == "vad"
    assert failed.error == "VAD provider disconnected"

    await pipeline.close()
