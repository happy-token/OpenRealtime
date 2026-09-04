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

pytestmark = pytest.mark.skipif(
    not (os.environ.get("RUN_LIVE") and os.environ.get("DOUBAO_API_KEY")),
    reason="requires RUN_LIVE=1 and a real DOUBAO_API_KEY against the direct Volcengine endpoint",
)

TEST_UTTERANCE = "今天天气怎么样"
_SAMPLE_RATE_HZ = 16000
_CHUNK_SIZE = 3200


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
