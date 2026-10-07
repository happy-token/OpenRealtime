from __future__ import annotations

from unittest.mock import Mock

import pytest

from server.realtime import (
    AppendSpeechText,
    CommitSpeech,
    InMemoryRealtimeConversation,
    StartSpeech,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import ReportPlaybackProgress, SpeechPlaybackProgress
from tests.realtime.test_speech_contract import context


@pytest.mark.parametrize("phase", ["started", "progress", "stopped", "completed"])
@pytest.mark.parametrize("precise", [False, True])
async def test_actual_speech_receipt_preserves_optional_sample_anchors(phase, precise):
    conversation = InMemoryRealtimeConversation(context=context())
    events = conversation.events()
    try:
        await conversation.send(
            StartSpeech(
                command_id="start", idempotency_key="start", context=context(), speech_id="speech"
            )
        )
        await anext(events)
        await conversation.send(
            AppendSpeechText(
                command_id="text",
                idempotency_key="text",
                context=context(),
                speech_id="speech",
                text_sequence=1,
                delta="测试",
            )
        )
        await anext(events)
        await conversation.send(
            CommitSpeech(
                command_id="commit", idempotency_key="commit", context=context(), speech_id="speech"
            )
        )
        await anext(events)
        await conversation.send(
            ReportPlaybackProgress(
                command_id="receipt",
                idempotency_key="receipt",
                context=context(),
                speech_id="speech",
                delivered_text_end=2,
                played_audio_end_us=1000,
                output_epoch="epoch" if precise else None,
                played_position_samples=16 if precise else None,
                sample_rate_hz=16000 if precise else None,
                observed_at_ns=1 if precise else None,
                started=phase == "started",
                stopped=phase == "stopped",
                completed=phase == "completed",
            )
        )
        progress = await anext(events)
        assert isinstance(progress, SpeechPlaybackProgress)
        assert getattr(progress, "output_epoch", None) == ("epoch" if precise else None)
        assert getattr(progress, "played_position_samples", None) == (16 if precise else None)
        assert getattr(progress, "sample_rate_hz", None) == (16000 if precise else None)
        telemetry = Mock()
        RealtimeTelemetryObserver(telemetry).observe_event(progress)
        call = next(
            call
            for call in telemetry.record.call_args_list
            if call.args[0] == "client.playback_progress"
        )
        attrs = call.kwargs["attributes"]
        assert attrs["output_epoch"] == ("epoch" if precise else None)
        assert attrs["played_position_samples"] == (16 if precise else None)
        assert attrs["sample_rate_hz"] == (16000 if precise else None)
        assert attrs["started"] == (phase == "started")
        assert attrs["stopped"] == (phase == "stopped")
        assert attrs["completed"] == (phase == "completed")
    finally:
        await conversation.close()
