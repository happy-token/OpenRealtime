import hashlib
import json
from pathlib import Path

import pytest

from scripts.benchmark_dh_live_v1_stability import (
    _preserve_failed_worker_evidence,
    _require_matching_causal_inputs,
    build_stability_notes,
    build_stability_worker_command,
    run_stability_benchmark,
    validate_stability_evidence,
)
from scripts.dh_live_v1_provider import RENDERER_FILES


def valid_stability_evidence(duration_seconds: int = 60) -> dict[str, object]:
    timestamps = [float(value) for value in range(0, duration_seconds * 1000 + 1, 40)]
    return {
        "canvas_width": 720,
        "canvas_height": 1280,
        "audio_bytes": 99_918,
        "requested_duration_ms": duration_seconds * 1000,
        "clip_duration_ms": 3_120,
        "set_audio_buffer_calls": 20,
        "audio_submission_timestamps_ms": [float(value) for value in range(0, 60_000, 3_120)],
        "timestamps_ms": timestamps,
        "blend_shape_deltas": [10.0] * len(timestamps),
        "browser_version": "HeadlessChrome/151",
        "webgl_version": "WebGL 2.0",
    }


def test_validate_stability_evidence_accepts_full_duration_callbacks() -> None:
    metrics = validate_stability_evidence(
        valid_stability_evidence(),
        expected_audio_bytes=99_918,
        expected_clip_seconds=3.12,
        expected_duration_seconds=60,
        significant_threshold=6.8,
    )

    assert metrics.renderer_update_samples == 1_501
    assert metrics.average_fps == pytest.approx(25)
    assert metrics.first_half_fps == pytest.approx(25)
    assert metrics.second_half_fps == pytest.approx(25)
    assert metrics.maximum_callback_gap_ms == 40
    assert metrics.speech_response_windows == 20
    assert metrics.minimum_significant_samples_per_window >= 3
    assert metrics.observation_seconds == 60


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"set_audio_buffer_calls": 19}, "repeat count"),
        ({"timestamps_ms": [0.0, 40.0, 39.0]}, "callback samples|monotonic"),
        (
            {
                "timestamps_ms": [float(value) for value in range(0, 59_001, 40)],
                "blend_shape_deltas": [10.0] * len(range(0, 59_001, 40)),
            },
            "requested duration",
        ),
        (
            {
                "timestamps_ms": [0.0, 40.0] + [float(v) for v in range(200, 60_001, 40)],
                "blend_shape_deltas": [10.0] * (2 + len(range(200, 60_001, 40))),
            },
            "gap exceeds",
        ),
        (
            {
                "timestamps_ms": [float(v) for v in range(0, 30_001, 40)]
                + [float(v) for v in range(30_050, 60_001, 50)],
                "blend_shape_deltas": [10.0]
                * (len(range(0, 30_001, 40)) + len(range(30_050, 60_001, 50))),
            },
            "FPS degrades",
        ),
        ({"blend_shape_deltas": [0.0] * 1_501}, "calibrated threshold"),
        (
            {
                "blend_shape_deltas": [
                    10.0 if value <= 2_400 else 0.0 for value in range(0, 60_001, 40)
                ],
            },
            "calibrated threshold",
        ),
        (
            {
                "audio_submission_timestamps_ms": [float(value) for value in range(0, 2_400, 120)],
                "blend_shape_deltas": [
                    10.0 if value <= 2_400 else 0.0 for value in range(0, 60_001, 40)
                ],
            },
            "cover every clip window",
        ),
        ({"webgl_version": "WebGL 1.0"}, "WebGL2"),
    ],
)
def test_validate_stability_evidence_rejects_incomplete_or_false_runs(
    changes: dict[str, object], message: str
) -> None:
    payload = valid_stability_evidence() | changes

    with pytest.raises(ValueError, match=message):
        validate_stability_evidence(
            payload,
            expected_audio_bytes=99_918,
            expected_clip_seconds=3.12,
            expected_duration_seconds=60,
            significant_threshold=6.8,
        )


def test_stability_worker_command_is_explicit() -> None:
    command = build_stability_worker_command(
        node_bin="/opt/node",
        worker=Path("worker.mjs"),
        renderer_url="http://127.0.0.1:8892/MiniLive.html",
        audio=Path("speech.wav"),
        evidence=Path("evidence.json"),
        duration_seconds=600,
        clip_duration_seconds=3.12,
    )

    assert command == [
        "/opt/node",
        "worker.mjs",
        "--renderer-url",
        "http://127.0.0.1:8892/MiniLive.html",
        "--audio",
        "speech.wav",
        "--evidence",
        "evidence.json",
        "--duration-ms",
        "600000",
        "--clip-duration-ms",
        "3120",
        "--canvas-width",
        "720",
        "--canvas-height",
        "1280",
    ]


def test_stability_notes_use_the_parameterized_causal_run() -> None:
    notes = build_stability_notes(
        causal_run_id="dh-live-mini-v1-custom-004",
        preview_artifact_id="dh-live-mini-v1-custom-004",
        clip_duration_seconds=3.12,
        set_audio_buffer_calls=193,
    )

    assert "references dh-live-mini-v1-custom-004" in notes
    assert "preview artifact is dh-live-mini-v1-custom-004" in notes
    assert "custom-003" not in notes


def test_run_rejects_rights_and_identity_before_external_work(tmp_path: Path) -> None:
    common = {
        "bundle": tmp_path / "bundle",
        "campaign": tmp_path / "campaign",
        "audio_path": tmp_path / "campaign/input.wav",
        "duration_seconds": 60,
        "causal_run_id": "causal-001",
        "preview_artifact_id": "causal-001",
    }
    with pytest.raises(ValueError, match="rights"):
        run_stability_benchmark(
            **common,
            run_id="valid",
            rights_confirmed=False,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="run identifiers"):
        run_stability_benchmark(
            **common,
            run_id="../unsafe",
            rights_confirmed=True,  # type: ignore[arg-type]
        )


def test_causal_alignment_rejects_a_different_avatar_or_audio() -> None:
    avatar = {"avatar_id": "shuchang", "manifest_sha256": "a" * 64}
    renderer = {"MiniLive.html": {"sha256": "b" * 64}}
    audio = {"size_bytes": 10, "sha256": "c" * 64, "duration_seconds": 3.12}
    causal = {"avatar": avatar, "renderer_files": renderer, "input": audio}

    _require_matching_causal_inputs(
        causal_reference=causal,
        avatar=avatar,
        renderer_files=renderer,
        input_provenance=audio,
    )
    with pytest.raises(ValueError, match="avatar bundle"):
        _require_matching_causal_inputs(
            causal_reference=causal,
            avatar=avatar | {"avatar_id": "different-person"},
            renderer_files=renderer,
            input_provenance=audio,
        )
    with pytest.raises(ValueError, match="audio"):
        _require_matching_causal_inputs(
            causal_reference=causal,
            avatar=avatar,
            renderer_files=renderer,
            input_provenance=audio | {"sha256": "d" * 64},
        )


def test_failed_worker_publish_rolls_back_raw_when_envelope_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "worker.json"
    raw.write_text('{"partial":true}\n', encoding="utf-8")
    raw_destination = tmp_path / "run.failed-worker.raw.json"
    envelope_destination = tmp_path / "run.failed-worker.json"
    staged_envelope = tmp_path / "staged-envelope.json"

    def fail_envelope_publish(staged: Path, destination: Path) -> None:
        if destination == envelope_destination:
            raise OSError("injected envelope failure")
        destination.hardlink_to(staged)

    monkeypatch.setattr(
        "scripts.benchmark_dh_live_v1_stability.publish_file_no_replace",
        fail_envelope_publish,
    )

    _preserve_failed_worker_evidence(
        raw_evidence=raw,
        raw_destination=raw_destination,
        envelope_destination=envelope_destination,
        staged_envelope=staged_envelope,
        run_id="failed-run",
        error=RuntimeError("worker failed"),
    )

    assert not raw_destination.exists()
    assert not envelope_destination.exists()


def test_campaign_long_run_is_self_consistent_and_keeps_realtime_gaps_null() -> None:
    campaign = Path(__file__).parents[1] / "research-assets/avatar-evaluation/2026-08-22"
    evidence = json.loads(
        (
            campaign / "runs/dh-live-v1-custom/dh-live-mini-v1-custom-long-003.evidence.json"
        ).read_text(encoding="utf-8")
    )
    canonical = json.loads(
        (campaign / "results/dh-live-mini-v1-custom-long-003.json").read_text(encoding="utf-8")
    )
    causal_path = campaign / evidence["causal_reference"]["evidence_path"]
    causal_hash = hashlib.sha256(causal_path.read_bytes()).hexdigest()
    metrics = validate_stability_evidence(
        evidence["worker"],
        expected_audio_bytes=evidence["input"]["size_bytes"],
        expected_clip_seconds=evidence["input"]["clip_duration_seconds"],
        expected_duration_seconds=evidence["input"]["requested_duration_seconds"],
        significant_threshold=evidence["causal_reference"]["silence_calibrated_threshold"],
    )

    assert metrics.__dict__ == evidence["metrics"]
    assert evidence["causal_reference"]["evidence_sha256"] == causal_hash
    assert evidence["schema_version"] == 2
    assert evidence["avatar"] == json.loads(causal_path.read_text(encoding="utf-8"))["avatar"]
    assert evidence["renderer_files"] == {
        relative.as_posix(): {"size_bytes": size, "sha256": digest}
        for relative, (size, digest) in RENDERER_FILES.items()
    }
    assert canonical["artifact_id"] == "dh-live-mini-v1-custom-003"
    assert canonical["stable_minutes"] == 10
    assert canonical["average_fps"] == metrics.average_fps
    assert canonical["second_half_fps"] == metrics.second_half_fps
    assert canonical["first_frame_ms"] is None
    assert canonical["av_drift_ms"] is None
    assert canonical["queue_growth"] is None
    assert canonical["interrupt_p95_ms"] is None
    assert canonical["thermal_state"] == "unknown"
