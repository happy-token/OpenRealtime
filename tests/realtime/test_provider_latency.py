from __future__ import annotations

from dataclasses import astuple
from unittest.mock import MagicMock

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.asr import (
    AppendAsrAudio,
    AsrTranscriptDelta,
    AsrTranscriptFinal,
    DiscardAsrInput,
)
from server.realtime.capabilities.tts import (
    AppendTtsText,
    TtsAudioFrame,
    TtsTextMode,
)
from server.realtime.protocol.audio import AudioEncoding, AudioFrame
from server.realtime.provider_latency import (
    ProviderLatencyObserver,
    ProviderLatencyTrace,
    TimedAsrSession,
    TimedTtsSession,
)


def test_four_provider_spans_use_host_delivery_boundaries() -> None:
    trace = ProviderLatencyTrace()
    trace.asr_audio_frame(at_ns=1_000_000_000)
    trace.asr_partial_text("你", at_ns=1_120_000_000)
    trace.asr_audio_frame(at_ns=1_250_000_000)
    trace.asr_final_text("你好", at_ns=1_340_000_000)
    trace.tts_text_chunk("你", at_ns=2_000_000_000)
    trace.tts_audio_chunk(b"pcm", at_ns=2_075_000_000)
    trace.llm_request(at_ns=3_000_000_000)
    trace.llm_text_chunk("你好", at_ns=3_062_000_000)

    metrics = trace.snapshot()
    assert metrics.asr_first_text_ms == 120
    assert metrics.asr_final_tail_ms == 90
    assert metrics.tts_first_audio_ms == 75
    assert metrics.llm_first_text_ms == 62


def test_empty_chunks_and_missing_results_never_create_zero_latency() -> None:
    trace = ProviderLatencyTrace()
    trace.asr_audio_frame(at_ns=1)
    trace.asr_partial_text("  ", at_ns=2)
    trace.asr_final_text("", at_ns=3)
    trace.tts_text_chunk(" ", at_ns=4)
    trace.tts_audio_chunk(b"", at_ns=5)
    trace.llm_request(at_ns=6)
    trace.llm_text_chunk(" ", at_ns=7)
    assert all(value is None for value in astuple(trace.snapshot()))


def test_first_text_can_arrive_as_final_but_tail_uses_last_frame() -> None:
    trace = ProviderLatencyTrace()
    trace.asr_audio_frame(at_ns=100)
    trace.asr_audio_frame(at_ns=200)
    trace.asr_final_text("你好", at_ns=250)
    assert trace.snapshot().asr_first_text_ms == 0.00015
    assert trace.snapshot().asr_final_tail_ms == 0.00005


def test_out_of_order_or_negative_timestamps_are_not_reported_as_latency() -> None:
    trace = ProviderLatencyTrace()
    trace.asr_audio_frame(at_ns=500)
    with pytest.raises(ValueError, match="delivery order"):
        trace.asr_audio_frame(at_ns=499)
    trace.asr_final_text("你好", at_ns=400)
    assert trace.snapshot().asr_final_tail_ms is None
    with pytest.raises(ValueError, match="non-negative"):
        trace.llm_request(at_ns=-1)


def test_audio_after_asr_final_cannot_rewrite_the_tail_boundary() -> None:
    trace = ProviderLatencyTrace()
    trace.asr_audio_frame(at_ns=1_000)
    trace.asr_partial_text("你", at_ns=1_100)
    trace.asr_final_text("你好", at_ns=1_200)
    with pytest.raises(ValueError, match="already produced final"):
        trace.asr_audio_frame(at_ns=1_300)
    assert trace.snapshot().asr_final_tail_ms == 0.0002


def _context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant", user_id="user", device_id="device",
        voice_session_id="voice", thread_id="thread", turn_id="turn", generation=1,
    )


def test_observer_isolates_same_generation_across_voice_sessions(monkeypatch) -> None:
    telemetry = MagicMock()
    timing = ProviderLatencyObserver(telemetry)
    first = _context()
    second = InteractionContext(
        tenant_id="tenant", user_id="user", device_id="device",
        voice_session_id="other-voice", thread_id="thread", turn_id="turn", generation=1,
    )
    ticks = iter((1_000_000_000, 2_000_000_000, 2_100_000_000, 1_200_000_000))
    monkeypatch.setattr("server.realtime.provider_latency.time.monotonic_ns", lambda: next(ticks))
    timing.asr_frame(first)
    timing.asr_frame(second)
    timing.asr_partial(second, "你")
    timing.asr_partial(first, "好")
    durations = [call.kwargs["duration_ms"] for call in telemetry.record.call_args_list]
    assert durations == [100, 200]


def _frame() -> AudioFrame:
    return AudioFrame(
        stream_id="stream", sequence=0, timestamp_us=0, duration_us=20_000,
        encoding=AudioEncoding.PCM_S16LE, sample_rate_hz=16_000,
        channels=1, data=b"\x00\x00",
    )


class _FakeSession:
    def __init__(self, events) -> None:
        self._events = events
        self.sent = []
        self.text_mode = TtsTextMode.DUPLEX

    async def send(self, command) -> None:
        self.sent.append(command)

    async def events(self):
        for event in self._events:
            yield event

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_timed_capability_wrappers_emit_asr_and_tts_host_boundary_spans(monkeypatch) -> None:
    telemetry = MagicMock()
    timing = ProviderLatencyObserver(telemetry)
    context = _context()
    ticks = iter((1_000_000_000, 1_100_000_000, 1_300_000_000,
                  2_000_000_000, 2_075_000_000))
    monkeypatch.setattr("server.realtime.provider_latency.time.monotonic_ns", lambda: next(ticks))

    asr = TimedAsrSession(_FakeSession([
        AsrTranscriptDelta(context=context, revision=1, delta="你", accumulated_text="你"),
        AsrTranscriptFinal(context=context, revision=1, text="你好", reason="end_of_turn"),
    ]), timing)
    await asr.send(AppendAsrAudio(frame=_frame(), context=context))
    assert len([event async for event in asr.events()]) == 2

    tts = TimedTtsSession(_FakeSession([
        TtsAudioFrame(context=context, speech_id="speech", frame=_frame(), is_final_for_segment=False),
    ]), timing, context)
    await tts.send(AppendTtsText(speech_id="speech", text_sequence=1, delta="你"))
    assert len([event async for event in tts.events()]) == 1

    durations = {call.args[0]: call.kwargs["duration_ms"] for call in telemetry.record.call_args_list}
    assert durations == {
        "asr.input_to_first_text": 100,
        "asr.last_frame_to_final_text": 300,
        "tts.first_text_to_first_audio": 75,
    }


@pytest.mark.asyncio
async def test_asr_discard_and_close_release_unfinished_timing_traces() -> None:
    timing = ProviderLatencyObserver(MagicMock())
    asr = TimedAsrSession(_FakeSession([]), timing)
    await asr.send(AppendAsrAudio(frame=_frame(), context=_context()))
    assert timing._asr
    await asr.send(DiscardAsrInput(reason="interrupted"))
    assert not timing._asr
    await asr.send(AppendAsrAudio(frame=_frame(), context=_context()))
    await asr.close()
    assert not timing._asr


def test_timing_spans_include_selected_instance_revision_without_content(monkeypatch) -> None:
    telemetry = MagicMock()
    timing = ProviderLatencyObserver(telemetry, instances={"asr": "instance-id"},
                                     versions={"asr": "config-version"})
    context = _context()
    ticks = iter((1_000_000_000, 1_150_000_000))
    monkeypatch.setattr("server.realtime.provider_latency.time.monotonic_ns", lambda: next(ticks))
    timing.asr_frame(context)
    timing.asr_partial(context, "private transcript")
    attributes = telemetry.record.call_args.kwargs["attributes"]
    assert attributes == {"instance_id": "instance-id", "config_version": "config-version"}
    assert "private transcript" not in str(telemetry.record.call_args)
