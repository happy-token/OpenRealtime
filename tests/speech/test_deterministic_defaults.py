"""Tests for the framework's deterministic speech defaults — PreloadedAsrEngine
and SilentTtsEngine — the "EchoLlmClient of ASR/TTS" used by tests and demos
when no real vendor conformer is configured.
"""

from server.speech.asr import PreloadedAsrEngine
from server.speech.tts import SilentTtsEngine, SynthesizedAudio, SynthesizedAudioChunk


async def test_preloaded_asr_session_returns_transcript_exactly_once():
    session = await PreloadedAsrEngine("hello world").start_session()

    first = await session.consume_transcript()
    second = await session.consume_transcript()

    assert first == "hello world"
    assert second == ""


async def test_preloaded_asr_session_ignores_pushed_audio():
    session = await PreloadedAsrEngine("hello world").start_session()

    await session.push_audio(b"\x00\x01", sample_rate_hz=16000)

    assert await session.consume_transcript() == "hello world"


async def test_preloaded_asr_session_close_is_a_no_op():
    session = await PreloadedAsrEngine("hello world").start_session()

    await session.close()


async def test_preloaded_asr_session_peek_transcript_does_not_clear_it():
    session = await PreloadedAsrEngine("hello world").start_session()

    first_peek = await session.peek_transcript()
    second_peek = await session.peek_transcript()

    assert first_peek == "hello world"
    assert second_peek == "hello world"
    assert await session.consume_transcript() == "hello world"


async def test_preloaded_asr_session_peek_transcript_is_empty_after_consume():
    session = await PreloadedAsrEngine("hello world").start_session()

    await session.consume_transcript()

    assert await session.peek_transcript() == ""


async def test_silent_tts_engine_returns_empty_audio_at_default_sample_rate():
    engine = SilentTtsEngine()

    audio = await engine.synthesize("anything")

    assert audio == SynthesizedAudio(pcm16=b"", sample_rate_hz=24000)


async def test_silent_tts_engine_honors_configured_sample_rate():
    engine = SilentTtsEngine(sample_rate_hz=16000)

    audio = await engine.synthesize("anything")

    assert audio == SynthesizedAudio(pcm16=b"", sample_rate_hz=16000)


async def test_silent_tts_engine_synthesize_stream_yields_one_empty_final_chunk():
    engine = SilentTtsEngine()

    chunks = [chunk async for chunk in engine.synthesize_stream("anything")]

    assert chunks == [SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=24000, is_final=True)]
