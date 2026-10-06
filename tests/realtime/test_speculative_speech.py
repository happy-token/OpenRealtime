from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from server.core.turn_content import TurnContent
from server.realtime.capabilities.speculative_speech import SpeculativeSpeechPipeline
from server.speech.tts import SynthesizedAudioChunk


class RecordingBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        self.calls += 1
        yield f"回复{turn.text}"


class GatedDuplexTts:
    def __init__(self) -> None:
        self.calls = 0
        self.audio_buffered = asyncio.Event()

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        self.calls += 1
        text = "".join([delta async for delta in text_stream])
        assert text
        self.audio_buffered.set()
        yield SynthesizedAudioChunk(
            pcm16=text.encode(),
            sample_rate_hz=16_000,
            is_final=False,
        )

    async def close(self) -> None:
        return None


@pytest.mark.parametrize("changed", ["association", "projection"])
async def test_changed_model_input_misses_text_and_audio_cache(changed):
    class EchoBrain:
        def __init__(self):
            self.turns = []

        async def stream(self, turn):
            self.turns.append(turn)
            yield turn.model_text

    brain, tts = EchoBrain(), GatedDuplexTts()
    pipeline = SpeculativeSpeechPipeline(brain=brain, tts=tts)
    original = TurnContent(text="上海呢", generation=2, conversation_context="北京晴")
    await pipeline.prepare(original)
    await asyncio.wait_for(tts.audio_buffered.wait(), .5)
    revised = replace(original, **({"input_relation_unresolved": True} if changed == "association"
                                 else {"context_projection_digest": "updated-heard-frontier"}))
    text = [delta async for delta in pipeline.stream(revised)]
    assert text == [revised.model_text]

    async def committed_text():
        for delta in text:
            yield delta

    audio = [chunk async for chunk in pipeline.synthesize_duplex(committed_text())]
    assert b"".join(chunk.pcm16 for chunk in audio) == revised.model_text.encode()
    assert brain.turns == [original, revised]


@pytest.mark.asyncio
async def test_prefetch_buffers_audio_and_reuses_one_brain_and_tts_call() -> None:
    brain = RecordingBrain()
    tts = GatedDuplexTts()
    pipeline = SpeculativeSpeechPipeline(brain=brain, tts=tts)
    turn = TurnContent(text="你好", generation=1)

    assert await pipeline.prepare(turn) is True
    await asyncio.wait_for(tts.audio_buffered.wait(), timeout=0.1)

    text = [delta async for delta in pipeline.stream(turn)]

    async def committed_text() -> AsyncIterator[str]:
        for delta in text:
            yield delta

    audio = [chunk async for chunk in pipeline.synthesize_duplex(committed_text())]

    assert text == ["回复你好"]
    assert [chunk.pcm16 for chunk in audio] == ["回复你好".encode()]
    assert brain.calls == 1
    assert tts.calls == 1


@pytest.mark.asyncio
async def test_revision_cancels_old_pipeline_and_prefetches_latest_turn() -> None:
    brain = RecordingBrain()
    tts = GatedDuplexTts()
    pipeline = SpeculativeSpeechPipeline(brain=brain, tts=tts)

    assert await pipeline.prepare(TurnContent(text="你好", generation=1)) is True
    await asyncio.wait_for(tts.audio_buffered.wait(), timeout=0.1)
    assert await pipeline.invalidate(1, reason="asr_increment") is True
    latest = TurnContent(text="你好呀", generation=1)
    assert await pipeline.prepare(latest) is True

    assert [delta async for delta in pipeline.stream(latest)] == ["回复你好呀"]
    assert brain.calls == 2
