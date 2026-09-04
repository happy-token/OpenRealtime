"""Benchmark a prepared custom DH_live_mini v1 avatar in the browser renderer."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import tempfile
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts.avatar_evaluation import BenchmarkRecord, append_benchmark_record
from scripts.benchmark_dh_live import (
    _required_executable,
    _run,
    _sha256,
    _write_json_staged,
    _write_silence_wav,
    build_browser_worker_command,
    load_browser_benchmark_evidence,
    probe_benchmark_wav,
    probe_normalized_video,
    publish_benchmark_files,
    snapshot_bounded_regular_file,
    validate_browser_benchmark_evidence,
)
from scripts.dh_live_v1_provider import (
    AVATAR_FILES,
    AVATAR_MANIFEST_NAME,
    DH_LIVE_V1_COMMIT,
    RENDERER_FILES,
    create_dh_live_v1_server,
    inspect_dh_live_v1_bundle,
)


def build_dh_live_v1_normalize_command(
    *,
    raw_video: Path,
    audio: Path,
    output: Path,
    duration_seconds: float,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and positive")
    return [
        ffmpeg_bin,
        "-nostdin",
        "-y",
        "-i",
        str(raw_video),
        "-i",
        str(audio),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        "fps=25,scale=720:1280:flags=lanczos,tpad=stop_mode=clone:stop_duration=0.200,format=yuv420p",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "24000",
        "-ac",
        "1",
        str(output),
    ]


def run_dh_live_v1_benchmark(
    *,
    bundle: Path,
    campaign: Path,
    audio_path: Path,
    output_path: Path,
    run_id: str,
    rights_confirmed: bool,
) -> dict[str, object]:
    if rights_confirmed is not True:
        raise ValueError("Audio and avatar evaluation rights must be confirmed")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", run_id):
        raise ValueError("run_id must contain only lowercase letters, numbers, and hyphens")
    campaign = campaign.resolve()
    bundle = bundle.resolve()
    audio_path = audio_path.resolve()
    output_path = output_path.resolve()
    if not output_path.is_relative_to(campaign / "runs"):
        raise ValueError("benchmark output must stay inside the campaign runs directory")
    if output_path.stem != run_id:
        raise ValueError("output filename must match run_id")
    if not audio_path.is_relative_to(campaign):
        raise ValueError("benchmark audio must stay inside the campaign directory")
    if output_path.exists() or output_path.with_suffix(".evidence.json").exists():
        raise FileExistsError(output_path)
    diagnostic = inspect_dh_live_v1_bundle(bundle)
    if not diagnostic.ready:
        raise RuntimeError("DH_live v1 avatar is not ready: " + "; ".join(diagnostic.issues))
    benchmark_path = campaign / "benchmark.csv"
    if not benchmark_path.is_file():
        raise FileNotFoundError(benchmark_path)

    node_bin = _required_executable("node")
    ffmpeg_bin = _required_executable("ffmpeg")
    ffprobe_bin = _required_executable("ffprobe")
    worker = Path(__file__).with_name("dh_live_browser_worker.mjs")
    evidence_path = output_path.with_suffix(".evidence.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".dh-live-v1-benchmark-", dir=output_path.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        audio_snapshot = temporary / "input.wav"
        snapshot_bounded_regular_file(audio_path, audio_snapshot, max_bytes=2_000_000)
        wav = probe_benchmark_wav(audio_snapshot)
        input_sha256 = _sha256(audio_snapshot)
        control_audio = temporary / "silence-control.wav"
        _write_silence_wav(control_audio, wav)
        control_wav = probe_benchmark_wav(control_audio)
        raw_video = temporary / "capture.webm"
        raw_evidence = temporary / "browser-evidence.json"
        normalized_video = temporary / "normalized.mp4"
        staged_evidence = temporary / "canonical-evidence.json"
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

        server = create_dh_live_v1_server(
            bundle_snapshot, port=0, usage_scope="internal_evaluation", allow_ephemeral=True
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _run(
                build_browser_worker_command(
                    node_bin=node_bin,
                    worker=worker,
                    renderer_url=f"http://127.0.0.1:{server.server_port}/MiniLive.html",
                    audio=audio_snapshot,
                    control_audio=control_audio,
                    raw_video=raw_video,
                    evidence=raw_evidence,
                    duration_seconds=wav.duration_seconds,
                    canvas_width=720,
                    canvas_height=1280,
                ),
                timeout=60,
            )
            browser_evidence = load_browser_benchmark_evidence(raw_evidence)
            metrics = validate_browser_benchmark_evidence(
                browser_evidence,
                expected_audio_bytes=wav.size_bytes,
                expected_control_audio_bytes=control_wav.size_bytes,
                expected_duration_seconds=wav.duration_seconds,
                expected_canvas_width=720,
                expected_canvas_height=1280,
            )
            _run(
                build_dh_live_v1_normalize_command(
                    raw_video=raw_video,
                    audio=audio_snapshot,
                    output=normalized_video,
                    duration_seconds=wav.duration_seconds,
                    ffmpeg_bin=ffmpeg_bin,
                )
            )
            normalized = probe_normalized_video(
                normalized_video,
                ffprobe_bin=ffprobe_bin,
                expected_duration_seconds=wav.duration_seconds,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        recorded_at = datetime.now(UTC).isoformat()
        output_relative = output_path.relative_to(campaign).as_posix()
        manifest = json.loads((bundle_snapshot / AVATAR_MANIFEST_NAME).read_text(encoding="utf-8"))
        evidence_payload: dict[str, object] = {
            "schema_version": 2,
            "run_id": run_id,
            "provider": "dh-live-mini-v1-custom",
            "recorded_at": recorded_at,
            "runtime_commit": DH_LIVE_V1_COMMIT,
            "avatar": {
                "avatar_id": diagnostic.avatar_id,
                "frame_count": diagnostic.frame_count,
                "manifest_sha256": _sha256(bundle_snapshot / AVATAR_MANIFEST_NAME),
                "source_video": manifest["source_video"],
                "files": manifest["files"],
                "authorized": diagnostic.authorized,
                "usage_scope": manifest["usage_scope"],
            },
            "input": {
                "path": audio_path.relative_to(campaign).as_posix(),
                "size_bytes": wav.size_bytes,
                "sha256": input_sha256,
                "duration_seconds": wav.duration_seconds,
                "sample_rate_hz": wav.sample_rate_hz,
                "channels": wav.channels,
                "sample_width_bytes": wav.sample_width_bytes,
            },
            "browser": asdict(browser_evidence),
            "renderer_files": {
                relative.as_posix(): {"size_bytes": size, "sha256": digest}
                for relative, (size, digest) in RENDERER_FILES.items()
            },
            "metrics": asdict(metrics),
            "metric_semantics": {
                "first_audio_driven_blend_change_ms": (
                    "First blend-shape delta above 3x the same-duration silence envelope; "
                    "not a visible frame or end-to-end latency."
                ),
                "playback_observation_seconds": (
                    "Paced browser observation window; not model compute time or comparable RTF."
                ),
            },
            "artifact": {
                "path": output_relative,
                "size_bytes": normalized.size_bytes,
                "sha256": _sha256(normalized_video),
                "duration_seconds": normalized.duration_seconds,
                "video_codec": normalized.video_codec,
                "audio_codec": normalized.audio_codec,
                "width": normalized.width,
                "height": normalized.height,
                "frame_rate": normalized.frame_rate,
                "video_frame_count": normalized.video_frame_count,
                "audio_sample_rate_hz": normalized.audio_sample_rate_hz,
                "video_duration_seconds": normalized.video_duration_seconds,
                "audio_duration_seconds": normalized.audio_duration_seconds,
                "audio_channels": normalized.audio_channels,
            },
            "limitations": [
                "Custom campaign portrait, but image and generated avatar authorization are not yet cleared for promotion.",
                "Visible MatesX watermark; internal evaluation only.",
                "Short-run browser benchmark; AV drift, interruption, and 10-minute stability remain unmeasured.",
                "DH_live v1 repository and generated-avatar commercial licensing remain unresolved.",
            ],
        }
        _write_json_staged(staged_evidence, evidence_payload)
        notes = (
            "Apple M1 browser WASM/WebGL2; custom campaign portrait via LivePortrait base video; "
            "silence-calibrated speech blend-shape response; visible MatesX watermark; internal only; "
            f"input_sha256={input_sha256}; evidence="
            f"{evidence_path.relative_to(campaign).as_posix()}; playback window is not compute RTF; "
            "AV drift, interruption, 10-minute stability, and commercial license pending"
        )
        record = BenchmarkRecord(
            run_id=run_id,
            provider="dh-live-mini-v1-custom",
            artifact_id=run_id,
            mode="realtime",
            status="experimental",
            recorded_at=recorded_at,
            duration_seconds=wav.duration_seconds,
            render_seconds=metrics.playback_observation_seconds,
            performance_metric_kind="paced_playback",
            average_fps=metrics.average_fps,
            first_frame_ms=None,
            stable_minutes=wav.duration_seconds / 60,
            second_half_fps=metrics.second_half_fps,
            thermal_state="unknown",
            notes=notes,
        )
        publish_benchmark_files(
            staged_video=normalized_video,
            staged_evidence=staged_evidence,
            output_path=output_path,
            evidence_path=evidence_path,
            append_record=lambda: append_benchmark_record(benchmark_path, record),
        )
        return evidence_payload


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
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rights-confirmed", action="store_true")
    args = parser.parse_args()
    payload = run_dh_live_v1_benchmark(
        bundle=args.bundle,
        campaign=args.campaign,
        audio_path=args.audio,
        output_path=args.output,
        run_id=args.run_id,
        rights_confirmed=args.rights_confirmed,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
