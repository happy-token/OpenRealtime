"""Live smoke test against the real Volcengine direct ASR endpoint — no
gateway, no browser. See server/speech/plugins/doubao_asr.py.

Feeds real synthesized speech (via DoubaoDirectTtsEngine) into
DoubaoAsrEngine to prove genuine speech-to-text works end-to-end through
the production single-key auth path, not just a handshake.

Skipped by default. Opt in with a real Doubao credential:

    RUN_LIVE=1 DOUBAO_API_KEY=<real key> uv run pytest tests/live/test_doubao_direct_asr_live.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

from server.speech.plugins.doubao_asr import DoubaoAsrEngine
from server.speech.plugins.doubao_tts_direct import DoubaoDirectTtsEngine
from server.speech.provider_contract_probe import execute_probe

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and os.environ.get("DOUBAO_API_KEY")),
    reason="requires RUN_LIVE=1 and a real DOUBAO_API_KEY against the direct Volcengine endpoint",
)

TEST_UTTERANCE = "今天天气怎么样"
_SAMPLE_RATE_HZ = 16000
_CHUNK_SIZE = 3200


async def test_live_duplex_tts_audio_before_text_end_then_asr_partial_and_final() -> None:
    """Exercise the realtime contract with real vendor calls, not a batch shortcut."""

    text_can_finish = asyncio.Event()
    text_finished = False

    async def text_stream():
        nonlocal text_finished
        yield "你好，今天我们一起测试实时语音合成。"
        await text_can_finish.wait()
        yield "现在继续说第二句话，确认文本和音频可以同时流动。"
        text_finished = True

    tts = DoubaoDirectTtsEngine(sample_rate_hz=_SAMPLE_RATE_HZ)
    audio_chunks: list[bytes] = []
    audio_before_text_end = False
    try:
        async with asyncio.timeout(30):
            async for chunk in tts.synthesize_duplex(text_stream()):
                if chunk.pcm16:
                    audio_before_text_end |= not text_finished
                    audio_chunks.append(chunk.pcm16)
                    text_can_finish.set()
                if chunk.is_final:
                    break
    finally:
        text_can_finish.set()
        await tts.close()

    assert audio_before_text_end, "TTS did not emit audio while the text stream remained open"
    assert text_finished
    assert audio_chunks

    asr = DoubaoAsrEngine(sample_rate_hz=_SAMPLE_RATE_HZ)
    session = await asr.start_session()
    partial_seen = False
    final_seen = False
    try:
        async with asyncio.timeout(30):
            for audio_chunk in audio_chunks:
                for i in range(0, len(audio_chunk), _CHUNK_SIZE):
                    frame = audio_chunk[i : i + _CHUNK_SIZE]
                    await session.push_audio(frame, sample_rate_hz=_SAMPLE_RATE_HZ)
                    await asyncio.sleep(len(frame) / 2 / _SAMPLE_RATE_HZ)
                    snapshot = await session.snapshot()
                    partial_seen |= bool(snapshot.text and not snapshot.is_sentence_end)
                    final_seen |= bool(snapshot.text and snapshot.is_sentence_end)
            for _ in range(15):
                if final_seen:
                    break
                await session.push_audio(b"\x00\x00" * 3200, sample_rate_hz=_SAMPLE_RATE_HZ)
                await asyncio.sleep(0.2)
                snapshot = await session.snapshot()
                partial_seen |= bool(snapshot.text and not snapshot.is_sentence_end)
                final_seen |= bool(snapshot.text and snapshot.is_sentence_end)
    finally:
        await session.close()

    assert partial_seen, "ASR did not expose non-final partial text"
    assert final_seen, "ASR did not expose final text"


async def test_live_transcribes_real_synthesized_speech() -> None:
    tts = DoubaoDirectTtsEngine(sample_rate_hz=_SAMPLE_RATE_HZ)
    audio = await tts.synthesize(TEST_UTTERANCE)

    asr = DoubaoAsrEngine(sample_rate_hz=_SAMPLE_RATE_HZ)
    session = await asr.start_session()
    try:
        for i in range(0, len(audio.pcm16), _CHUNK_SIZE):
            chunk = audio.pcm16[i : i + _CHUNK_SIZE]
            await session.push_audio(chunk, sample_rate_hz=_SAMPLE_RATE_HZ)
            # Exercise the streaming service at microphone cadence. Blasting
            # an entire utterance into the socket in one event-loop turn is not
            # representative and can outrun vendor-side stream admission.
            await asyncio.sleep(len(chunk) / 2 / _SAMPLE_RATE_HZ)
        # The bidirectional endpoint finalizes while audio continues streaming;
        # unlike a browser's always-on mic, synthesized audio stops at its last
        # sample. Keep feeding silence (up to three seconds) until the vendor's
        # async definite event arrives. The configured endpoint window is the
        # acoustic threshold, not a hard response-time guarantee.
        snapshot = await session.snapshot()
        for _ in range(15):
            await session.push_audio(b"\x00\x00" * 3200, sample_rate_hz=_SAMPLE_RATE_HZ)
            await asyncio.sleep(0.2)
            snapshot = await session.snapshot()
            if snapshot.is_sentence_end:
                break
        transcript = snapshot.text
    finally:
        await session.close()

    assert TEST_UTTERANCE in transcript
    assert snapshot.is_sentence_end is True


async def test_live_personal_asr_contract_probe_with_env_key() -> None:
    """Exercise the same partial/final probe used by personal provider tests."""
    key = os.environ["DOUBAO_API_KEY"]
    result = await execute_probe({
        "capability": "asr", "provider": "doubao", "apiKey": key,
        "fixtureTtsKey": key,
    })
    assert result["ok"] is True, result["message"]
    assert isinstance(result["firstOutputMs"], (int, float))
