from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendSpeechText,
    CommitSpeech,
    RealtimeConversation,
    RequestResponse,
    SpeechStarted,
    SpeechTextAccepted,
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
from server.realtime.native import NativeRealtimeEngine
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryStatus,
)
from server.signals.energy_vad import EnergyVad, EnergyVadConfig
from server.speech.asr import PreloadedAsrEngine
from server.speech.tts import SynthesizedAudioChunk
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


class SilentBrain:
    async def stream(self, turn) -> AsyncIterator[str]:
        del turn
        if False:
            yield ""


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


class NativeProviderSession:
    def __init__(self) -> None:
        self._events: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

    async def send(self, message) -> None:
        del message

    async def events(self):
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        await self._events.put(None)


class NativeProvider:
    def __init__(self) -> None:
        self.session = NativeProviderSession()

    async def open(self, *, context, profile):
        del context, profile
        return self.session


@dataclass(slots=True)
class ContractConversation:
    conversation: RealtimeConversation
    deliveries: InMemorySpeechDeliveryStore


async def open_contract_conversation(engine_kind: str) -> ContractConversation:
    deliveries = InMemorySpeechDeliveryStore()
    tts = LegacyTtsCapabilityAdapter(EchoDuplexTts())
    if engine_kind == "native":
        engine = NativeRealtimeEngine(
            provider=NativeProvider(),
            tts=tts,
            speech_deliveries=deliveries,
        )
    else:
        engine = CascadedRealtimeEngine(
            vad=LegacyVadCapabilityAdapter(
                lambda: EnergyVad(
                    EnergyVadConfig(
                        energy_threshold=500,
                        silence_duration_ms=32,
                    )
                )
            ),
            asr=LegacyAsrCapabilityAdapter(PreloadedAsrEngine("unused")),
            turn_manager=LegacyTurnManagerCapabilityAdapter(TurnPolicy),
            brain=LegacyBrainCapabilityAdapter(SilentBrain()),
            speech_renderer=DeterministicSpeechRenderer(),
            tts=tts,
            speech_deliveries=deliveries,
        )
    return ContractConversation(
        conversation=await engine.open(context=context(), profile=None),
        deliveries=deliveries,
    )


@pytest.mark.parametrize("engine_kind", ["cascaded", "native"])
async def test_engine_contract_external_speech_is_ordered_and_idempotent(
    engine_kind: str,
) -> None:
    opened = await open_contract_conversation(engine_kind)
    conversation = opened.conversation
    events = conversation.events()
    start = StartSpeech(
        command_id="start-1",
        idempotency_key="start-1",
        context=context(),
        speech_id="speech-1",
    )
    await conversation.send(start)
    await conversation.send(start)
    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), SpeechStarted)

    await conversation.send(
        AppendSpeechText(
            command_id="text-1",
            idempotency_key="text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="第一段",
        )
    )
    emitted = []
    while not any(isinstance(event, SpeechTextAccepted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    assert sum(isinstance(event, SpeechStarted) for event in emitted) == 0

    await conversation.send(
        CommitSpeech(
            command_id="commit-1",
            idempotency_key="commit-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    while not any(isinstance(event, SpeechTextCommitted) for event in emitted):
        emitted.append(await asyncio.wait_for(anext(events), timeout=0.2))
    committed = next(
        event for event in emitted if isinstance(event, SpeechTextCommitted)
    )
    assert committed.spoken_text == "第一段"
    await conversation.close()


@pytest.mark.parametrize("engine_kind", ["cascaded", "native"])
async def test_engine_contract_rejects_a_second_output_lane(
    engine_kind: str,
) -> None:
    opened = await open_contract_conversation(engine_kind)
    conversation = opened.conversation
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    with pytest.raises(ValueError, match="active"):
        await conversation.send(
            RequestResponse(
                command_id="response-1",
                idempotency_key="response-1",
                context=replace(context(), response_id="response-1"),
                response_id="response-1",
                minimum_thread_sequence=0,
            )
        )

    await conversation.close()


@pytest.mark.parametrize("engine_kind", ["cascaded", "native"])
async def test_engine_contract_close_marks_unplayed_speech_uncertain(
    engine_kind: str,
) -> None:
    opened = await open_contract_conversation(engine_kind)
    conversation = opened.conversation
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="text-1",
            idempotency_key="text-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="尚未确认播放",
        )
    )
    await conversation.send(
        CommitSpeech(
            command_id="commit-1",
            idempotency_key="commit-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    await conversation.close()

    record = await opened.deliveries.get("speech-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.UNCERTAIN
    assert record.delivered_speech_transcript == ""
