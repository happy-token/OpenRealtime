"""Run a long, non-recording browser stability benchmark for a custom DH_live v1 avatar."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import tempfile
import threading
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from scripts.avatar_evaluation import BenchmarkRecord, append_benchmark_record
from scripts.benchmark_dh_live import (
    _required_executable,
    _run,
    _sha256,
    _write_json_staged,
    probe_benchmark_wav,
    publish_file_no_replace,
    snapshot_bounded_regular_file,
)
from scripts.dh_live_v1_provider import (
    AVATAR_FILES,
    AVATAR_MANIFEST_NAME,
    DH_LIVE_V1_COMMIT,
    RENDERER_FILES,
    create_dh_live_v1_server,
    inspect_dh_live_v1_bundle,
)

STABILITY_FIELDS = {
    "canvas_width",
    "canvas_height",
    "audio_bytes",
    "requested_duration_ms",
    "clip_duration_ms",
    "set_audio_buffer_calls",
    "audio_submission_timestamps_ms",
    "timestamps_ms",
    "blend_shape_deltas",
    "browser_version",
    "webgl_version",
}


@dataclass(frozen=True)
class StabilityMetrics:
    renderer_update_samples: int
    average_fps: float
    first_half_fps: float
    second_half_fps: float
    maximum_callback_gap_ms: float
    significant_speech_samples: int
    speech_response_windows: int
    minimum_significant_samples_per_window: int
    observation_seconds: float


def _load_worker_evidence(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid DH_live stability evidence")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid DH_live stability evidence") from error
    if type(payload) is not dict or set(payload) != STABILITY_FIELDS:
        raise ValueError("DH_live stability evidence has an unexpected schema")
    return payload


def validate_stability_evidence(
    payload: dict[str, object],
    *,
    expected_audio_bytes: int,
    expected_clip_seconds: float,
    expected_duration_seconds: float,
    significant_threshold: float,
) -> StabilityMetrics:
    if any(field not in payload for field in STABILITY_FIELDS):
        raise ValueError("stability evidence is missing required fields")
    if not math.isfinite(significant_threshold) or significant_threshold <= 0:
        raise ValueError("stability speech threshold must be finite and positive")
    integer_fields = (
        "canvas_width",
        "canvas_height",
        "audio_bytes",
        "requested_duration_ms",
        "clip_duration_ms",
        "set_audio_buffer_calls",
    )
    if any(type(payload[field]) is not int for field in integer_fields):
        raise ValueError("stability evidence integer field is invalid")
    if payload["canvas_width"] != 720 or payload["canvas_height"] != 1280:
        raise ValueError("unexpected stability canvas dimensions")
    if payload["audio_bytes"] != expected_audio_bytes:
        raise ValueError("stability audio size mismatch")
    expected_duration_ms = round(expected_duration_seconds * 1000)
    expected_clip_ms = round(expected_clip_seconds * 1000)
    if (
        payload["requested_duration_ms"] != expected_duration_ms
        or payload["clip_duration_ms"] != expected_clip_ms
        or payload["set_audio_buffer_calls"] != math.ceil(expected_duration_ms / expected_clip_ms)
    ):
        raise ValueError("stability duration or repeat count mismatch")
    timestamps = payload["timestamps_ms"]
    deltas = payload["blend_shape_deltas"]
    submission_timestamps = payload["audio_submission_timestamps_ms"]
    if (
        type(timestamps) is not list
        or type(deltas) is not list
        or type(submission_timestamps) is not list
        or len(timestamps) != len(deltas)
        or len(submission_timestamps) != payload["set_audio_buffer_calls"]
        or len(timestamps) < math.floor(expected_duration_seconds * 20)
        or any(
            type(value) not in (int, float)
            for value in (*timestamps, *deltas, *submission_timestamps)
        )
    ):
        raise ValueError("stability callback samples are invalid")
    timestamp_values = tuple(float(value) for value in timestamps)
    delta_values = tuple(float(value) for value in deltas)
    submission_values = tuple(float(value) for value in submission_timestamps)
    if any(
        not math.isfinite(value) or value < 0
        for value in (*timestamp_values, *delta_values, *submission_values)
    ):
        raise ValueError("stability callback samples must be finite and non-negative")
    if any(right <= left for left, right in pairwise(timestamp_values)):
        raise ValueError("stability timestamps must be strictly monotonic")
    if any(right <= left for left, right in pairwise(submission_values)):
        raise ValueError("stability audio submissions must be strictly monotonic")
    if (
        submission_values[0] > 120
        or not expected_duration_ms - expected_clip_ms - 120
        <= submission_values[-1]
        < expected_duration_ms
        or any(
            not expected_clip_ms - 120 <= right - left <= expected_clip_ms + 120
            for left, right in pairwise(submission_values)
        )
    ):
        raise ValueError("stability audio submissions do not cover every clip window")
    if timestamp_values[0] > 120 or timestamp_values[-1] < expected_duration_ms - 120:
        raise ValueError("stability callbacks do not cover the requested duration")
    if timestamp_values[-1] > expected_duration_ms + 120:
        raise ValueError("stability callbacks exceed the requested duration")
    maximum_gap = max(right - left for left, right in pairwise(timestamp_values))
    if maximum_gap > 120:
        raise ValueError("stability callback gap exceeds 120ms")
    if type(payload["browser_version"]) is not str or not payload["browser_version"].strip():
        raise ValueError("stability browser version is missing")
    if (
        type(payload["webgl_version"]) is not str
        or "webgl 2" not in payload["webgl_version"].lower()
    ):
        raise ValueError("stability benchmark requires WebGL2")
    significant_samples = sum(value > significant_threshold for value in delta_values)
    significant_per_window: list[int] = []
    for index, window_start in enumerate(submission_values):
        window_end = (
            submission_values[index + 1]
            if index + 1 < len(submission_values)
            else expected_duration_ms + 120
        )
        sample_start = bisect_left(timestamp_values, window_start)
        sample_end = bisect_left(timestamp_values, window_end)
        significant_per_window.append(
            sum(value > significant_threshold for value in delta_values[sample_start:sample_end])
        )
    if not significant_per_window or min(significant_per_window) < 3:
        raise ValueError("stability speech response is below the calibrated threshold")

    midpoint = expected_duration_ms / 2
    first_half = tuple(value for value in timestamp_values if value <= midpoint)
    second_half = tuple(value for value in timestamp_values if value >= midpoint)
    average_fps = _fps(timestamp_values)
    first_half_fps = _fps(first_half)
    second_half_fps = _fps(second_half)
    if (
        average_fps < 24.9
        or first_half_fps < 24.9
        or second_half_fps < 24.9
        or second_half_fps < first_half_fps * 0.98
    ):
        raise ValueError("stability renderer FPS degrades below the acceptance threshold")
    return StabilityMetrics(
        renderer_update_samples=len(timestamp_values),
        average_fps=average_fps,
        first_half_fps=first_half_fps,
        second_half_fps=second_half_fps,
        maximum_callback_gap_ms=maximum_gap,
        significant_speech_samples=significant_samples,
        speech_response_windows=len(significant_per_window),
        minimum_significant_samples_per_window=min(significant_per_window),
        observation_seconds=(timestamp_values[-1] - timestamp_values[0]) / 1000,
    )


def _fps(timestamps_ms: tuple[float, ...]) -> float:
    if len(timestamps_ms) < 2:
        raise ValueError("insufficient timestamps for FPS")
    return (len(timestamps_ms) - 1) * 1000 / (timestamps_ms[-1] - timestamps_ms[0])


def build_stability_worker_command(
    *,
    node_bin: str,
    worker: Path,
    renderer_url: str,
    audio: Path,
    evidence: Path,
    duration_seconds: float,
    clip_duration_seconds: float,
) -> list[str]:
    if not math.isfinite(duration_seconds) or not 1 <= duration_seconds <= 660:
        raise ValueError("stability duration must be between 1 and 660 seconds")
    if not math.isfinite(clip_duration_seconds) or not 0.1 <= clip_duration_seconds <= 60:
        raise ValueError("clip duration must be between 0.1 and 60 seconds")
    return [
        node_bin,
        str(worker),
        "--renderer-url",
        renderer_url,
        "--audio",
        str(audio),
        "--evidence",
        str(evidence),
        "--duration-ms",
        str(round(duration_seconds * 1000)),
        "--clip-duration-ms",
        str(round(clip_duration_seconds * 1000)),
        "--canvas-width",
        "720",
        "--canvas-height",
        "1280",
    ]


def build_stability_notes(
    *,
    causal_run_id: str,
    preview_artifact_id: str,
    clip_duration_seconds: float,
    set_audio_buffer_calls: int,
) -> str:
    return (
        "DH_live v1 custom browser renderer callback stability; "
        f"{clip_duration_seconds:.2f}s input repeated {set_audio_buffer_calls} times; "
        f"causal speech proof references {causal_run_id}; no long-run media capture, "
        "AV drift, visible latency, interruption, queue depth, or thermal evidence; "
        f"preview artifact is {preview_artifact_id}"
    )


def _load_causal_reference(path: Path, *, expected_run_id: str) -> dict[str, object]:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload["schema_version"] != 2
            or payload["provider"] != "dh-live-mini-v1-custom"
            or payload["run_id"] != expected_run_id
            or type(payload["avatar"]) is not dict
            or type(payload["input"]) is not dict
            or type(payload["renderer_files"]) is not dict
            or not math.isfinite(float(payload["metrics"]["silence_calibrated_threshold"]))
        ):
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"{expected_run_id} causal reference is missing or invalid") from error
    return payload


def _avatar_provenance(bundle: Path, diagnostic: object) -> dict[str, object]:
    manifest_path = bundle / AVATAR_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "avatar_id": diagnostic.avatar_id,
        "frame_count": diagnostic.frame_count,
        "manifest_sha256": _sha256(manifest_path),
        "source_video": manifest["source_video"],
        "files": manifest["files"],
        "authorized": diagnostic.authorized,
        "usage_scope": manifest["usage_scope"],
    }


def _require_matching_causal_inputs(
    *,
    causal_reference: dict[str, object],
    avatar: dict[str, object],
    renderer_files: dict[str, object],
    input_provenance: dict[str, object],
) -> None:
    if causal_reference["avatar"] != avatar:
        raise ValueError("stability avatar bundle does not match the causal reference")
    if causal_reference["renderer_files"] != renderer_files:
        raise ValueError("stability renderer does not match the causal reference")
    causal_input = causal_reference["input"]
    if not isinstance(causal_input, dict) or any(
        causal_input.get(field) != input_provenance[field]
        for field in ("size_bytes", "sha256", "duration_seconds")
    ):
        raise ValueError("stability audio does not match the causal reference")


def _preserve_failed_worker_evidence(
    *,
    raw_evidence: Path,
    raw_destination: Path,
    envelope_destination: Path,
    staged_envelope: Path,
    run_id: str,
    error: BaseException,
) -> None:
    raw: dict[str, object] | None = None
    try:
        if (
            raw_evidence.is_file()
            and not raw_evidence.is_symlink()
            and 0 < raw_evidence.stat().st_size <= 16 * 1024 * 1024
        ):
            raw = {
                "path": raw_destination.name,
                "size_bytes": raw_evidence.stat().st_size,
                "sha256": _sha256(raw_evidence),
            }
            publish_file_no_replace(raw_evidence, raw_destination)
        _write_json_staged(
            staged_envelope,
            {
                "schema_version": 1,
                "run_id": run_id,
                "failure_type": type(error).__name__,
                "failure_message": str(error)[:2_000],
                "raw_worker_evidence": raw,
            },
        )
        publish_file_no_replace(staged_envelope, envelope_destination)
    except (OSError, ValueError):
        for staged, published in (
            (staged_envelope, envelope_destination),
            (raw_evidence, raw_destination),
        ):
            try:
                if published.exists() and staged.exists() and published.samefile(staged):
                    published.unlink()
            except OSError:
                continue
        return


def run_stability_benchmark(
    *,
    bundle: Path,
    campaign: Path,
    audio_path: Path,
    run_id: str,
    causal_run_id: str,
    preview_artifact_id: str,
    duration_seconds: float,
    rights_confirmed: bool,
) -> dict[str, object]:
    if rights_confirmed is not True:
        raise ValueError("Audio and avatar evaluation rights must be confirmed")
    identifiers = {
        "run_id": run_id,
        "causal_run_id": causal_run_id,
        "preview_artifact_id": preview_artifact_id,
    }
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) for value in identifiers.values()):
        raise ValueError(
            "run identifiers must contain only lowercase letters, numbers, and hyphens"
        )
    if not math.isfinite(duration_seconds) or not 60 <= duration_seconds <= 660:
        raise ValueError("stability duration must be between 60 and 660 seconds")
    campaign = campaign.resolve()
    bundle = bundle.resolve()
    audio_path = audio_path.resolve()
    if not audio_path.is_relative_to(campaign):
        raise ValueError("stability audio must stay inside the campaign")
    evidence_path = campaign / f"runs/dh-live-v1-custom/{run_id}.evidence.json"
    failed_evidence_path = campaign / f"runs/dh-live-v1-custom/{run_id}.failed-worker.json"
    failed_raw_path = campaign / f"runs/dh-live-v1-custom/{run_id}.failed-worker.raw.json"
    if evidence_path.exists() or failed_evidence_path.exists() or failed_raw_path.exists():
        raise FileExistsError(evidence_path)
    diagnostic = inspect_dh_live_v1_bundle(bundle)
    if not diagnostic.ready:
        raise RuntimeError("DH_live v1 avatar is not ready: " + "; ".join(diagnostic.issues))
    benchmark_path = campaign / "benchmark.csv"
    if not benchmark_path.is_file():
        raise FileNotFoundError(benchmark_path)
    causal_path = campaign / f"runs/dh-live-v1-custom/{causal_run_id}.evidence.json"
    node_bin = _required_executable("node")
    worker = Path(__file__).with_name("dh_live_stability_worker.mjs")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".dh-live-v1-stability-", dir=evidence_path.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        audio_snapshot = temporary / "input.wav"
        snapshot_bounded_regular_file(audio_path, audio_snapshot, max_bytes=2_000_000)
        wav = probe_benchmark_wav(audio_snapshot)
        raw_evidence = temporary / "worker.json"
        staged_evidence = temporary / "evidence.json"
        staged_failure = temporary / "failure.json"
        causal_snapshot = temporary / "causal-reference.json"
        snapshot_bounded_regular_file(causal_path, causal_snapshot, max_bytes=2 * 1024 * 1024)
        causal_reference = _load_causal_reference(causal_snapshot, expected_run_id=causal_run_id)
        threshold = float(causal_reference["metrics"]["silence_calibrated_threshold"])
        bundle_snapshot = temporary / "bundle"
        bundle_snapshot.mkdir()
        for relative in (*RENDERER_FILES, *AVATAR_FILES, Path(AVATAR_MANIFEST_NAME)):
            source = bundle / relative
            destination = bundle_snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        snapshot_diagnostic = inspect_dh_live_v1_bundle(bundle_snapshot)
        if not snapshot_diagnostic.ready:
            raise RuntimeError(
                "DH_live v1 snapshot is not ready: " + "; ".join(snapshot_diagnostic.issues)
            )
        avatar = _avatar_provenance(bundle_snapshot, snapshot_diagnostic)
        renderer_files = {
            relative.as_posix(): {"size_bytes": size, "sha256": digest}
            for relative, (size, digest) in RENDERER_FILES.items()
        }
        input_provenance = {
            "size_bytes": wav.size_bytes,
            "sha256": _sha256(audio_snapshot),
            "duration_seconds": wav.duration_seconds,
        }
        _require_matching_causal_inputs(
            causal_reference=causal_reference,
            avatar=avatar,
            renderer_files=renderer_files,
            input_provenance=input_provenance,
        )
        if preview_artifact_id != causal_run_id:
            raise ValueError("preview artifact must be the causal short-run artifact")

        server = create_dh_live_v1_server(
            bundle_snapshot, port=0, usage_scope="internal_evaluation", allow_ephemeral=True
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            try:
                _run(
                    build_stability_worker_command(
                        node_bin=node_bin,
                        worker=worker,
                        renderer_url=f"http://127.0.0.1:{server.server_port}/MiniLive.html",
                        audio=audio_snapshot,
                        evidence=raw_evidence,
                        duration_seconds=duration_seconds,
                        clip_duration_seconds=wav.duration_seconds,
                    ),
                    timeout=round(duration_seconds) + 90,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            worker_evidence = _load_worker_evidence(raw_evidence)
            metrics = validate_stability_evidence(
                worker_evidence,
                expected_audio_bytes=wav.size_bytes,
                expected_clip_seconds=wav.duration_seconds,
                expected_duration_seconds=duration_seconds,
                significant_threshold=threshold,
            )
        except BaseException as error:
            _preserve_failed_worker_evidence(
                raw_evidence=raw_evidence,
                raw_destination=failed_raw_path,
                envelope_destination=failed_evidence_path,
                staged_envelope=staged_failure,
                run_id=run_id,
                error=error,
            )
            raise
        recorded_at = datetime.now(UTC).isoformat()
        payload: dict[str, object] = {
            "schema_version": 2,
            "run_id": run_id,
            "provider": "dh-live-mini-v1-custom",
            "recorded_at": recorded_at,
            "runtime_commit": DH_LIVE_V1_COMMIT,
            "stability_metric_kind": "browser_renderer_callbacks",
            "input": {
                "path": audio_path.relative_to(campaign).as_posix(),
                "size_bytes": wav.size_bytes,
                "sha256": _sha256(audio_snapshot),
                "clip_duration_seconds": wav.duration_seconds,
                "requested_duration_seconds": duration_seconds,
            },
            "avatar": avatar,
            "causal_reference": {
                "run_id": causal_reference["run_id"],
                "evidence_path": causal_path.relative_to(campaign).as_posix(),
                "evidence_sha256": _sha256(causal_snapshot),
                "silence_calibrated_threshold": threshold,
            },
            "worker": worker_evidence,
            "metrics": metrics.__dict__,
            "renderer_files": renderer_files,
            "preview": {
                "artifact_id": preview_artifact_id,
                "relationship": (
                    f"{wav.duration_seconds:.2f}-second short preview; "
                    f"not the {duration_seconds:.0f}-second stability artifact"
                ),
            },
            "limitations": [
                "Renderer callback stability only; no 600-second video was recorded.",
                "Visible-frame latency, image lip-sync error, AV drift, interruption, queue depth, and thermal state remain unmeasured.",
                "MatesX watermark and commercial licensing remain unresolved; internal evaluation only.",
            ],
        }
        _write_json_staged(staged_evidence, payload)
        observation_seconds = metrics.observation_seconds
        record = BenchmarkRecord(
            run_id=run_id,
            provider="dh-live-mini-v1-custom",
            artifact_id=preview_artifact_id,
            mode="realtime",
            status="experimental",
            recorded_at=recorded_at,
            duration_seconds=duration_seconds,
            render_seconds=observation_seconds,
            performance_metric_kind="paced_playback",
            average_fps=metrics.average_fps,
            first_frame_ms=None,
            stable_minutes=duration_seconds / 60,
            second_half_fps=metrics.second_half_fps,
            thermal_state="unknown",
            notes=build_stability_notes(
                causal_run_id=causal_run_id,
                preview_artifact_id=preview_artifact_id,
                clip_duration_seconds=wav.duration_seconds,
                set_audio_buffer_calls=int(worker_evidence["set_audio_buffer_calls"]),
            ),
        )
        try:
            publish_file_no_replace(staged_evidence, evidence_path)
            append_benchmark_record(benchmark_path, record)
        except BaseException:
            evidence_path.unlink(missing_ok=True)
            raise
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(
            "research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/shuchang-avatar"
        ),
    )
    parser.add_argument(
        "--campaign",
        type=Path,
        default=Path("research-assets/avatar-evaluation/2026-08-22"),
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=Path("research-assets/avatar-evaluation/2026-08-22/inputs/wav2lip-speech-3s.wav"),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--causal-run-id", required=True)
    parser.add_argument("--preview-artifact-id", required=True)
    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--rights-confirmed", action="store_true")
    args = parser.parse_args()
    payload = run_stability_benchmark(
        bundle=args.bundle,
        campaign=args.campaign,
        audio_path=args.audio,
        run_id=args.run_id,
        causal_run_id=args.causal_run_id,
        preview_artifact_id=args.preview_artifact_id,
        duration_seconds=args.duration,
        rights_confirmed=args.rights_confirmed,
    )
    print(
        json.dumps(
            {
                "run_id": payload["run_id"],
                "metrics": payload["metrics"],
                "evidence": str(
                    args.campaign / f"runs/dh-live-v1-custom/{args.run_id}.evidence.json"
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
