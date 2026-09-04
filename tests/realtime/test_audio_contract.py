from __future__ import annotations

from server.realtime import AudioEncoding, AudioFrame


def test_audio_frame_carries_negotiated_format_on_one_media_timeline() -> None:
    frame = AudioFrame(
        stream_id="microphone-1",
        sequence=7,
        timestamp_us=1_000_000,
        duration_us=20_000,
        encoding=AudioEncoding.OPUS,
        sample_rate_hz=48_000,
        channels=2,
        data=b"opus-frame",
    )

    assert frame.end_timestamp_us == 1_020_000
    assert frame.encoding is AudioEncoding.OPUS
    assert frame.sample_rate_hz == 48_000
    assert frame.channels == 2
