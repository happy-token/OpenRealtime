"""Utilities for building repeatable digital-human evaluation assets."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BENCHMARK_FIELDS = [
    "run_id",
    "provider",
    "artifact_id",
    "mode",
    "status",
    "recorded_at",
    "duration_seconds",
    "render_seconds",
    "rtf",
    "performance_metric_kind",
    "average_fps",
    "first_frame_ms",
    "av_drift_ms",
    "stable_minutes",
    "queue_growth",
    "interrupt_p95_ms",
    "second_half_fps",
    "thermal_state",
    "notes",
]

SUPPORTED_BENCHMARK_MODES = {"offline", "realtime"}
SUPPORTED_BENCHMARK_STATUSES = {"ready", "experimental", "failed", "blocked"}
SUPPORTED_THERMAL_STATES = {"", "nominal", "fair", "serious", "critical", "unknown"}
UTC_TZ = timezone.utc  # noqa: UP017 -- shared benchmark helpers support Python 3.10 runtimes.


class CanonicalResultError(ValueError):
    """Raised when a canonical benchmark run is malformed or conflicting."""


@dataclass(frozen=True)
class StaticBaseVideoSpec:
    """Output contract for a normalized, silent static avatar base video."""

    portrait_path: Path
    output_path: Path
    duration_seconds: float = 5.0
    width: int = 720
    height: int = 1280
    fps: int = 25


@dataclass(frozen=True)
class BenchmarkRecord:
    """One comparable avatar rendering result."""

    run_id: str
    provider: str
    artifact_id: str
    mode: str
    status: str
    duration_seconds: float
    render_seconds: float
    performance_metric_kind: str = "compute"
    average_fps: float | None = None
    first_frame_ms: float | None = None
    av_drift_ms: float | None = None
    stable_minutes: float | None = None
    queue_growth: float | None = None
    interrupt_p95_ms: float | None = None
    second_half_fps: float | None = None
    thermal_state: str = ""
    recorded_at: str | None = None
    notes: str = ""


def build_static_base_video_command(
    spec: StaticBaseVideoSpec,
    *,
    ffmpeg_bin: str = "ffmpeg",
    overwrite: bool = False,
) -> list[str]:
    """Build the FFmpeg command without executing it."""

    _validate_static_video_spec(spec)

    video_filter = (
        f"fps={spec.fps},"
        f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease:out_range=tv,"
        f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2,"
        "format=yuv420p"
    )
    command = [ffmpeg_bin, "-nostdin"]
    if overwrite:
        command.append("-y")
    command.extend(
        [
            "-loop",
            "1",
            "-i",
            str(spec.portrait_path),
            "-t",
            f"{spec.duration_seconds:.3f}",
            "-vf",
            video_filter,
            "-r",
            str(spec.fps),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-an",
            str(spec.output_path),
        ]
    )
    return command


def initialize_campaign(
    workspace: Path,
    *,
    campaign_id: str,
    portrait_path: Path,
    usage_scope: str,
    rights_confirmed: bool,
) -> tuple[Path, Path]:
    """Create a shared, auditable workspace for comparing avatar providers."""

    if not rights_confirmed:
        raise ValueError("Portrait rights must be confirmed before creating a campaign")
    if not portrait_path.is_file():
        raise FileNotFoundError(portrait_path)

    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError(f"Campaign workspace is non-empty: {workspace}")

    workspace.mkdir(parents=True, exist_ok=True)
    inputs_path = workspace / "inputs"
    inputs_path.mkdir(exist_ok=True)
    (workspace / "runs").mkdir(exist_ok=True)
    (workspace / "artifacts").mkdir(exist_ok=True)

    portrait_copy = inputs_path / f"portrait{portrait_path.suffix.lower()}"
    shutil.copy2(portrait_path, portrait_copy)
    portrait_bytes = portrait_copy.read_bytes()

    manifest_path = workspace / "manifest.json"
    manifest = {
        "campaign_id": campaign_id,
        "inputs": {
            "portrait": {
                "path": portrait_copy.relative_to(workspace).as_posix(),
                "sha256": hashlib.sha256(portrait_bytes).hexdigest(),
                "size_bytes": len(portrait_bytes),
            },
        },
        "usage_scope": usage_scope,
        "rights": {
            "internal_processing_confirmed": rights_confirmed,
            "public_distribution_confirmed": False,
        },
        "target": {
            "width": 720,
            "height": 1280,
            "fps": 25,
            "video_codec": "h264",
            "audio_sample_rate_hz": 24000,
        },
        "realtime_acceptance": {
            "minimum_fps": 25,
            "maximum_rtf": 0.8,
            "maximum_first_frame_ms": 1500,
            "maximum_av_drift_ms": 80,
            "minimum_stable_minutes": 10,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    benchmark_path = workspace / "benchmark.csv"
    with benchmark_path.open("w", newline="", encoding="utf-8") as benchmark_file:
        csv.writer(benchmark_file).writerow(BENCHMARK_FIELDS)

    return manifest_path, benchmark_path


def append_benchmark_record(benchmark_path: Path, record: BenchmarkRecord) -> None:
    """Atomically persist one canonical run and rebuild the derived CSV."""

    if not benchmark_path.is_file():
        raise FileNotFoundError(benchmark_path)

    with benchmark_path.open(newline="", encoding="utf-8") as benchmark_file:
        header = next(csv.reader(benchmark_file), None)
    if header != BENCHMARK_FIELDS:
        raise ValueError("Benchmark CSV schema does not match the current format")

    if record.mode not in SUPPORTED_BENCHMARK_MODES:
        raise ValueError(f"Unsupported benchmark mode: {record.mode}")
    if record.status not in SUPPORTED_BENCHMARK_STATUSES:
        raise ValueError(f"Unsupported benchmark status: {record.status}")
    if record.thermal_state not in SUPPORTED_THERMAL_STATES:
        raise ValueError(f"Unsupported thermal state: {record.thermal_state}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record.artifact_id):
        raise ValueError("artifact_id must contain only lowercase letters, numbers, and hyphens")

    _validate_metric("duration_seconds", record.duration_seconds, positive=True)
    for field_name in (
        "render_seconds",
        "average_fps",
        "first_frame_ms",
        "av_drift_ms",
        "stable_minutes",
        "queue_growth",
        "interrupt_p95_ms",
        "second_half_fps",
    ):
        value = getattr(record, field_name)
        if value is not None:
            _validate_metric(field_name, value)

    realtime_factor = record.render_seconds / record.duration_seconds
    result_payload = {
        "run_id": record.run_id,
        "provider": record.provider,
        "artifact_id": record.artifact_id,
        "mode": record.mode,
        "status": record.status,
        "recorded_at": record.recorded_at or datetime.now(UTC_TZ).isoformat(),
        "duration_seconds": record.duration_seconds,
        "render_seconds": record.render_seconds,
        "rtf": realtime_factor,
        "performance_metric_kind": record.performance_metric_kind,
        "average_fps": record.average_fps,
        "first_frame_ms": record.first_frame_ms,
        "av_drift_ms": record.av_drift_ms,
        "stable_minutes": record.stable_minutes,
        "queue_growth": record.queue_growth,
        "interrupt_p95_ms": record.interrupt_p95_ms,
        "second_half_fps": record.second_half_fps,
        "thermal_state": record.thermal_state,
        "notes": record.notes,
    }
    _validate_result_payload(result_payload, source=f"new run {record.run_id}")

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record.run_id):
        raise ValueError("run_id must contain only lowercase letters, numbers, and hyphens")

    results_directory = benchmark_path.with_name("results")
    results_directory.mkdir(exist_ok=True)
    lock_path = results_directory / ".write.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        canonical_results = _load_canonical_results(results_directory)
        existing_result = next(
            (result for result in canonical_results if result["run_id"] == record.run_id),
            None,
        )
        if existing_result is not None and _without_recorded_at(
            existing_result
        ) != _without_recorded_at(result_payload):
            raise ValueError(f"Conflicting benchmark run_id: {record.run_id}")
        created_result = existing_result is None
        if created_result:
            _write_canonical_result(results_directory, record.run_id, result_payload)
            canonical_results.append(result_payload)
        try:
            _rebuild_benchmark_csv(benchmark_path, canonical_results)
        except BaseException:
            if created_result:
                (results_directory / f"{record.run_id}.json").unlink(missing_ok=True)
            raise


def _write_canonical_result(
    results_directory: Path,
    run_id: str,
    payload: dict[str, object],
) -> None:
    destination = results_directory / f"{run_id}.json"
    with tempfile.NamedTemporaryFile(
        "w",
        dir=results_directory,
        prefix=f".{run_id}.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as temporary_file:
        json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(destination)


def _load_canonical_results(results_directory: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen_run_ids: set[str] = set()
    for result_path in sorted(results_directory.glob("*.json")):
        try:
            candidate = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CanonicalResultError(
                f"Invalid canonical result {result_path}: {error}"
            ) from error
        if not isinstance(candidate, dict):
            raise CanonicalResultError(
                f"Invalid canonical result {result_path}: expected an object"
            )
        _validate_result_payload(candidate, source=str(result_path))
        run_id = candidate["run_id"]
        if run_id != result_path.stem or run_id in seen_run_ids:
            raise CanonicalResultError(
                f"Invalid canonical result {result_path}: conflicting run_id"
            )
        seen_run_ids.add(run_id)
        results.append(candidate)
    return results


def _rebuild_benchmark_csv(
    benchmark_path: Path,
    canonical_results: list[dict[str, object]],
) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        dir=benchmark_path.parent,
        prefix=".benchmark.",
        suffix=".tmp",
        delete=False,
        newline="",
        encoding="utf-8",
    ) as temporary_file:
        writer = csv.DictWriter(temporary_file, fieldnames=BENCHMARK_FIELDS)
        writer.writeheader()
        for result in sorted(canonical_results, key=lambda item: str(item["run_id"])):
            writer.writerow(_benchmark_csv_row(result))
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(benchmark_path)


def _benchmark_csv_row(result: dict[str, object]) -> dict[str, str]:
    def metric(field_name: str) -> str:
        value = result.get(field_name)
        return "" if value is None else f"{float(value):.3f}"

    return {
        "run_id": _escape_spreadsheet_formula(str(result["run_id"])),
        "provider": _escape_spreadsheet_formula(str(result["provider"])),
        "artifact_id": _escape_spreadsheet_formula(str(result["artifact_id"])),
        "mode": _escape_spreadsheet_formula(str(result["mode"])),
        "status": _escape_spreadsheet_formula(str(result["status"])),
        "recorded_at": _escape_spreadsheet_formula(str(result["recorded_at"])),
        "duration_seconds": metric("duration_seconds"),
        "render_seconds": metric("render_seconds"),
        "rtf": metric("rtf"),
        "performance_metric_kind": _escape_spreadsheet_formula(
            str(result.get("performance_metric_kind", "compute"))
        ),
        "average_fps": metric("average_fps"),
        "first_frame_ms": metric("first_frame_ms"),
        "av_drift_ms": metric("av_drift_ms"),
        "stable_minutes": metric("stable_minutes"),
        "queue_growth": metric("queue_growth"),
        "interrupt_p95_ms": metric("interrupt_p95_ms"),
        "second_half_fps": metric("second_half_fps"),
        "thermal_state": _escape_spreadsheet_formula(str(result["thermal_state"])),
        "notes": _escape_spreadsheet_formula(str(result["notes"])),
    }


def _without_recorded_at(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "recorded_at"}


def _validate_result_payload(payload: dict[str, object], *, source: str) -> None:
    def invalid(field_name: str, reason: str) -> CanonicalResultError:
        return CanonicalResultError(f"Invalid canonical result {source}: {field_name} {reason}")

    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", run_id):
        raise invalid("run_id", "has an invalid format")
    provider = payload.get("provider")
    if not isinstance(provider, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider):
        raise invalid("provider", "has an invalid format")
    artifact_id = payload.get("artifact_id")
    if not isinstance(artifact_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", artifact_id):
        raise invalid("artifact_id", "has an invalid format")
    if payload.get("mode") not in SUPPORTED_BENCHMARK_MODES:
        raise invalid("mode", "is unsupported")
    if payload.get("status") not in SUPPORTED_BENCHMARK_STATUSES:
        raise invalid("status", "is unsupported")
    if payload.get("thermal_state") not in SUPPORTED_THERMAL_STATES:
        raise invalid("thermal_state", "is unsupported")
    if payload.get("performance_metric_kind", "compute") not in {"compute", "paced_playback"}:
        raise invalid("performance_metric_kind", "is unsupported")
    if not isinstance(payload.get("notes"), str):
        raise invalid("notes", "must be a string")

    recorded_at = payload.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise invalid("recorded_at", "must be an ISO-8601 string")
    try:
        parsed_recorded_at = datetime.fromisoformat(recorded_at)
    except ValueError as error:
        raise invalid("recorded_at", "must be a valid ISO-8601 timestamp") from error
    if parsed_recorded_at.tzinfo is None:
        raise invalid("recorded_at", "must include a timezone")

    numeric_fields = {
        "duration_seconds": True,
        "render_seconds": False,
        "rtf": False,
    }
    optional_numeric_fields = (
        "average_fps",
        "first_frame_ms",
        "av_drift_ms",
        "stable_minutes",
        "queue_growth",
        "interrupt_p95_ms",
        "second_half_fps",
    )
    for field_name, positive in numeric_fields.items():
        value = payload.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid(field_name, "must be numeric")
        try:
            _validate_metric(field_name, value, positive=positive)
        except ValueError as error:
            raise invalid(field_name, str(error)) from error
    for field_name in optional_numeric_fields:
        value = payload.get(field_name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid(field_name, "must be numeric or null")
        try:
            _validate_metric(field_name, value)
        except ValueError as error:
            raise invalid(field_name, str(error)) from error

    expected_rtf = float(payload["render_seconds"]) / float(payload["duration_seconds"])
    if not math.isclose(float(payload["rtf"]), expected_rtf, rel_tol=1e-9, abs_tol=1e-12):
        raise invalid("rtf", "does not match render_seconds / duration_seconds")


def render_static_base_video(
    spec: StaticBaseVideoSpec,
    *,
    ffmpeg_bin: str = "ffmpeg",
    overwrite: bool = False,
    runner: Callable[..., object] = subprocess.run,
) -> list[str]:
    """Render a static base video and return the executed command."""

    if not spec.portrait_path.is_file():
        raise FileNotFoundError(spec.portrait_path)
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_static_base_video_command(
        spec,
        ffmpeg_bin=ffmpeg_bin,
        overwrite=overwrite,
    )
    runner(command, check=True)
    return command


def _validate_static_video_spec(spec: StaticBaseVideoSpec) -> None:
    _validate_metric("duration_seconds", spec.duration_seconds, positive=True)
    if not 1 <= spec.fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    for name, value in (("width", spec.width), ("height", spec.height)):
        if not 64 <= value <= 8192 or value % 2:
            raise ValueError(f"{name} must be an even integer between 64 and 8192")


def _validate_metric(name: str, value: float, *, positive: bool = False) -> None:
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be a finite {qualifier} number")


def _escape_spreadsheet_formula(value: str) -> str:
    stripped_value = value.lstrip()
    if value.startswith(("\t", "\r", "\n")) or stripped_value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare normalized assets for digital-human evaluation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an evaluation campaign")
    init_parser.add_argument("workspace", type=Path)
    init_parser.add_argument("--campaign-id", required=True)
    init_parser.add_argument("--portrait", required=True, type=Path)
    init_parser.add_argument("--usage-scope", default="internal_evaluation")
    init_parser.add_argument("--rights-confirmed", action="store_true")

    static_parser = subparsers.add_parser("static", help="Render a static base video")
    static_parser.add_argument("portrait", type=Path)
    static_parser.add_argument("output", type=Path)
    static_parser.add_argument("--duration", type=float, default=5.0)
    static_parser.add_argument("--width", type=int, default=720)
    static_parser.add_argument("--height", type=int, default=1280)
    static_parser.add_argument("--fps", type=int, default=25)
    static_parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    static_parser.add_argument("--force", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., object] = subprocess.run,
) -> int:
    """Command-line entry point used by local evaluation runs."""

    args = _build_parser().parse_args(argv)
    if args.command == "init":
        initialize_campaign(
            args.workspace,
            campaign_id=args.campaign_id,
            portrait_path=args.portrait,
            usage_scope=args.usage_scope,
            rights_confirmed=args.rights_confirmed,
        )
        return 0

    render_static_base_video(
        StaticBaseVideoSpec(
            portrait_path=args.portrait,
            output_path=args.output,
            duration_seconds=args.duration,
            width=args.width,
            height=args.height,
            fps=args.fps,
        ),
        ffmpeg_bin=args.ffmpeg_bin,
        overwrite=args.force,
        runner=runner,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
