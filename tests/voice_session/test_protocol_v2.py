from __future__ import annotations

import pytest

from server.voice_session.protocol import (
    AudioFormat,
    AudioGap,
    CaptureMode,
    DeviceCaptureProfile,
    InputAudioAck,
    InputAudioFrame,
    InputEpochStarted,
    InputEpochTimeline,
    ProtocolIncompatible,
    SessionHello,
)


def test_v2_handshake_requires_an_explicit_supported_version_overlap() -> None:
    hello = SessionHello(supported_protocol_versions=(3, 2))

    assert hello.negotiate(server_supported_versions=(2,)) == 2

    with pytest.raises(ProtocolIncompatible):
        SessionHello(supported_protocol_versions=(1,)).negotiate(
            server_supported_versions=(2,)
        )


def test_input_epoch_acknowledges_only_a_contiguous_sample_timeline() -> None:
    timeline = InputEpochTimeline()
    timeline.start(
        InputEpochStarted(
            input_epoch="input-1",
            format=AudioFormat(format_id="pcm16-16k-mono"),
            requested_profile=DeviceCaptureProfile(),
            effective_profile=DeviceCaptureProfile(),
        )
    )

    result = timeline.accept(
        InputAudioFrame(
            input_epoch="input-1",
            sequence=0,
            start_sample=0,
            sample_count=512,
            capture_mode=CaptureMode.PREBUFFER,
            pcm16_base64="AAA=",
        )
    )

    assert result == InputAudioAck(
        input_epoch="input-1",
        highest_contiguous_sequence=0,
        next_start_sample=512,
    )


def test_input_epoch_reports_a_gap_without_advancing_the_ack_boundary() -> None:
    timeline = InputEpochTimeline()
    timeline.start(
        InputEpochStarted(
            input_epoch="input-1",
            format=AudioFormat(format_id="pcm16-16k-mono"),
            requested_profile=DeviceCaptureProfile(),
            effective_profile=DeviceCaptureProfile(),
        )
    )

    gap = timeline.accept(
        InputAudioFrame(
            input_epoch="input-1",
            sequence=1,
            start_sample=512,
            sample_count=512,
            capture_mode=CaptureMode.LIVE,
            pcm16_base64="AAA=",
        )
    )

    assert gap == AudioGap(
        input_epoch="input-1",
        expected_sequence=0,
        received_sequence=1,
        expected_start_sample=0,
        received_start_sample=512,
    )
