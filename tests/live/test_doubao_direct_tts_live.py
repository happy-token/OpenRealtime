"""Live smoke test against the real Volcengine direct bidirectional TTS
endpoint — no gateway, no browser. See
server/speech/plugins/doubao_tts_direct.py.

Skipped by default. Opt in with a real Doubao credential:

    RUN_LIVE=1 DOUBAO_API_KEY=<real key> uv run pytest tests/live/test_doubao_direct_tts_live.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

from server.speech.plugins.doubao_tts_direct import DoubaoDirectTtsEngine

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and os.environ.get("DOUBAO_API_KEY")),
    reason="requires RUN_LIVE=1 and a real DOUBAO_API_KEY against the direct Volcengine endpoint",
)

TEST_UTTERANCE = "今天天气怎么样"


async def test_live_synthesize_returns_real_pcm16_audio() -> None:
    engine = DoubaoDirectTtsEngine()

    audio = await engine.synthesize(TEST_UTTERANCE)

    assert len(audio.pcm16) > 0
    assert audio.sample_rate_hz > 0


async def test_live_synthesize_stream_yields_audio_then_final_chunk() -> None:
    engine = DoubaoDirectTtsEngine()

    chunks = [chunk async for chunk in engine.synthesize_stream(TEST_UTTERANCE)]

    assert len(chunks) >= 2
    assert chunks[-1].is_final
    assert chunks[-1].pcm16 == b""
    assert sum(len(chunk.pcm16) for chunk in chunks) > 0


async def test_live_duplex_stream_accepts_incremental_text_and_returns_audio() -> None:
    engine = DoubaoDirectTtsEngine()

    async def text_stream():
        yield "双向流式"
        await asyncio.sleep(0.05)
        yield "语音合成测试。"

    try:
        chunks = [chunk async for chunk in engine.synthesize_duplex(text_stream())]
    finally:
        await engine.close()

    assert chunks[-1].is_final
    assert chunks[-1].pcm16 == b""
    assert sum(len(chunk.pcm16) for chunk in chunks) > 0
