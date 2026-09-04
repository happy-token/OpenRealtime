import socket
import wave
from pathlib import Path

import pytest

from scripts.benchmark_livetalking import (
    LIVETALKING_METRIC_KINDS,
    StreamObservation,
    _require_port_available,
    _validate_audio_source,
    _validate_run_id,
    build_canonical_benchmark_record,
    build_repeated_pcm_wav,
    derive_stability_metrics,
)


def _write_pcm_wav(path: Path, *, frames: int = 16_000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x01\x00" * frames)


def test_build_repeated_pcm_wav_creates_exact_bounded_duration(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "long.wav"
    _write_pcm_wav(source, frames=8_000)

    result = build_repeated_pcm_wav(source, output, duration_seconds=3.12)

    assert result.duration_seconds == 3.12
    assert result.sample_rate_hz == 16_000
    with wave.open(str(output), "rb") as generated:
        assert generated.getnframes() == 49_920
        assert generated.readframes(1) == b"\x01\x00"

    with pytest.raises(ValueError, match="600"):
        build_repeated_pcm_wav(source, output, duration_seconds=600.1)


def test_run_id_requires_a_canonical_identifier() -> None:
    _validate_run_id("livetalking-wav2lip96-interrupt-002")

    for value in ("", "-", "leading-", "Uppercase", "contains_underscore"):
        with pytest.raises(ValueError, match="run_id"):
            _validate_run_id(value)


def test_port_preflight_rejects_an_existing_listener() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            _require_port_available(port)
    finally:
        listener.close()

    _require_port_available(port)


def test_audio_source_must_be_a_bounded_regular_file(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF")
    assert _validate_audio_source(source) == source.resolve()

    link = tmp_path / "source-link.wav"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="regular"):
        _validate_audio_source(link)

    oversized = tmp_path / "oversized.wav"
    oversized.write_bytes(b"\0" * (32 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="32 MiB"):
        _validate_audio_source(oversized)


def valid_observation() -> StreamObservation:
    video_arrivals = tuple(float(value) for value in range(1_000, 602_001, 40))
    video_media = tuple(value - 1_000 for value in video_arrivals)
    audio_arrivals = tuple(float(value) for value in range(1_000, 602_001, 20))
    audio_media = tuple(value - 1_000 for value in audio_arrivals)
    return StreamObservation(
        connected_ms=900.0,
        video_arrival_ms=video_arrivals,
        video_media_ms=video_media,
        audio_arrival_ms=audio_arrivals,
        audio_media_ms=audio_media,
        speaking_start_ms=1_050.0,
        speaking_end_ms=601_050.0,
        interrupt_latencies_ms=(90.0, 110.0, 130.0, 150.0, 170.0),
    )


def test_derive_stability_metrics_measures_full_realtime_contract() -> None:
    metrics = derive_stability_metrics(valid_observation(), expected_duration_seconds=600)

    assert metrics.stable_minutes == pytest.approx(10.0, abs=0.01)
    assert metrics.average_fps == pytest.approx(25.0, abs=0.01)
    assert metrics.second_half_fps == pytest.approx(25.0, abs=0.01)
    assert metrics.first_frame_ms == 100.0
    assert metrics.av_drift_ms == pytest.approx(0.0)
    assert metrics.queue_growth_frames == pytest.approx(0.0)
    assert metrics.interrupt_p95_ms == pytest.approx(170.0)


def test_canonical_record_does_not_promote_non_acceptance_observations() -> None:
    observation = valid_observation()
    metrics = derive_stability_metrics(observation, expected_duration_seconds=600)

    record = build_canonical_benchmark_record(
        run_id="livetalking-semantic-test",
        recorded_at="2026-08-23T00:00:00+08:00",
        duration_seconds=600,
        observation=observation,
        metrics=metrics,
        evidence_relative_path="runs/livetalking/test.evidence.json",
    )

    assert record.first_frame_ms is None
    assert record.av_drift_ms is None
    assert record.queue_growth is None
    assert record.interrupt_p95_ms is None
    assert record.average_fps == pytest.approx(25.0, abs=0.01)
    assert "idle_webrtc_first_frame_ms=100.000" in record.notes
    assert "receiver_frame_deficit=0.000" in record.notes
    assert LIVETALKING_METRIC_KINDS == {
        "first_frame_ms": "webrtc_idle_connection_frame",
        "av_drift_ms": "rtp_media_clock_p99",
        "queue_growth_frames": "receiver_frame_deficit",
        "interrupt_p95_ms": "server_output_state",
    }


def test_av_drift_uses_stability_window_and_p99_instead_of_a_single_outlier() -> None:
    observation = valid_observation()
    video_media = list(observation.video_media_ms)
    video_media[0] += 40
    stable_outlier = next(
        index
        for index, arrival in enumerate(observation.video_arrival_ms)
        if arrival >= observation.speaking_start_ms
    )
    video_media[stable_outlier] += 20

    metrics = derive_stability_metrics(
        StreamObservation(**(observation.__dict__ | {"video_media_ms": tuple(video_media)})),
        expected_duration_seconds=600,
    )

    assert metrics.av_drift_ms == pytest.approx(0.0)
    assert metrics.queue_growth_frames == pytest.approx(0.0)


def test_stability_metrics_reject_a_long_midstream_gap() -> None:
    observation = valid_observation()
    keep = tuple(range(5_000)) + tuple(range(5_030, len(observation.video_arrival_ms)))

    with pytest.raises(ValueError, match="gap"):
        derive_stability_metrics(
            StreamObservation(
                **(
                    observation.__dict__
                    | {
                        "video_arrival_ms": tuple(observation.video_arrival_ms[i] for i in keep),
                        "video_media_ms": tuple(observation.video_media_ms[i] for i in keep),
                    }
                )
            ),
            expected_duration_seconds=600,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"video_arrival_ms": (1_000.0, 1_040.0)}, "incomplete"),
        (
            {"audio_media_ms": (-1.0,) + valid_observation().audio_media_ms[1:]},
            "non-negative",
        ),
        ({"interrupt_latencies_ms": (100.0,)}, "interrupt"),
        ({"speaking_end_ms": 0.0}, "speaking"),
    ],
)
def test_derive_stability_metrics_rejects_incomplete_evidence(
    changes: dict[str, object], message: str
) -> None:
    values = valid_observation().__dict__ | changes

    with pytest.raises(ValueError, match=message):
        derive_stability_metrics(StreamObservation(**values), expected_duration_seconds=600)
