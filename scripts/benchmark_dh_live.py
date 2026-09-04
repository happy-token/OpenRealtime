"""Run and validate a browser-side DH_live_mini audio benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlsplit

from scripts.avatar_evaluation import BenchmarkRecord, append_benchmark_record
from scripts.dh_live_provider import (
    DH_LIVE_COMMIT,
    DHLiveRuntime,
    create_dh_live_server,
    inspect_dh_live_runtime,
)

EVIDENCE_FIELDS = {
    "canvas_width",
    "canvas_height",
    "speech_audio_bytes",
    "control_audio_bytes",
    "set_audio_buffer_calls",
    "control_timestamps_ms",
    "control_blend_shape_deltas",
    "speech_timestamps_ms",
    "speech_blend_shape_deltas",
    "browser_version",
    "webgl_version",
}


@dataclass(frozen=True)
class BrowserBenchmarkEvidence:
    canvas_width: int
    canvas_height: int
    speech_audio_bytes: int
    control_audio_bytes: int
    set_audio_buffer_calls: int
    control_timestamps_ms: tuple[float, ...]
    control_blend_shape_deltas: tuple[float, ...]
    speech_timestamps_ms: tuple[float, ...]
    speech_blend_shape_deltas: tuple[float, ...]
    browser_version: str
    webgl_version: str


@dataclass(frozen=True)
class BrowserBenchmarkMetrics:
    renderer_update_samples: int
    average_fps: float
    second_half_fps: float
    first_audio_driven_blend_change_ms: float
    silence_calibrated_threshold: float
    silence_max_delta: float
    speech_max_delta: float
    significant_speech_samples: int
    playback_observation_seconds: float


@dataclass(frozen=True)
class BenchmarkWav:
    path: Path
    size_bytes: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int


@dataclass(frozen=True)
class NormalizedVideo:
    duration_seconds: float
    size_bytes: int
    video_codec: str
    audio_codec: str
    width: int
    height: int
    frame_rate: float
    video_frame_count: int
    audio_sample_rate_hz: int
    video_duration_seconds: float
    audio_duration_seconds: float
    audio_channels: int


def load_browser_benchmark_evidence(path: Path) -> BrowserBenchmarkEvidence:
    """Load the exact browser-worker schema without accepting JS boolean-as-number values."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid browser benchmark evidence: {path}") from error
    if type(payload) is not dict or set(payload) != EVIDENCE_FIELDS:
        raise ValueError("browser benchmark evidence has an unexpected schema")

    integer_fields = (
        "canvas_width",
        "canvas_height",
        "speech_audio_bytes",
        "control_audio_bytes",
        "set_audio_buffer_calls",
    )
    for field_name in integer_fields:
        if type(payload[field_name]) is not int:
            raise ValueError(f"{field_name} must be an integer")
    array_fields = (
        "control_timestamps_ms",
        "control_blend_shape_deltas",
        "speech_timestamps_ms",
        "speech_blend_shape_deltas",
    )
    for field_name in array_fields:
        values = payload[field_name]
        if type(values) is not list or any(type(value) not in (int, float) for value in values):
            raise ValueError(f"{field_name} must be a numeric array")
    for field_name in ("browser_version", "webgl_version"):
        if type(payload[field_name]) is not str:
            raise ValueError(f"{field_name} must be a string")

    return BrowserBenchmarkEvidence(
        canvas_width=payload["canvas_width"],
        canvas_height=payload["canvas_height"],
        speech_audio_bytes=payload["speech_audio_bytes"],
        control_audio_bytes=payload["control_audio_bytes"],
        set_audio_buffer_calls=payload["set_audio_buffer_calls"],
        control_timestamps_ms=tuple(float(value) for value in payload["control_timestamps_ms"]),
        control_blend_shape_deltas=tuple(
            float(value) for value in payload["control_blend_shape_deltas"]
        ),
        speech_timestamps_ms=tuple(float(value) for value in payload["speech_timestamps_ms"]),
        speech_blend_shape_deltas=tuple(
            float(value) for value in payload["speech_blend_shape_deltas"]
        ),
        browser_version=payload["browser_version"],
        webgl_version=payload["webgl_version"],
    )


def probe_benchmark_wav(path: Path) -> BenchmarkWav:
    """Require the exact PCM input contract consumed by this benchmark."""

    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frames = source.getnframes()
            compression = source.getcomptype()
            actual_pcm_bytes = len(source.readframes(frames + 1))
    except (wave.Error, EOFError) as error:
        raise ValueError("benchmark audio must be a valid WAV file") from error
    if (channels, sample_width, sample_rate, compression) != (1, 2, 16_000, "NONE"):
        raise ValueError("benchmark audio must be PCM16 mono at 16kHz")
    if frames <= 0:
        raise ValueError("benchmark audio cannot be empty")
    size_bytes = path.stat().st_size
    expected_pcm_bytes = frames * channels * sample_width
    if actual_pcm_bytes != expected_pcm_bytes:
        raise ValueError("benchmark audio has a truncated PCM payload")
    if size_bytes > expected_pcm_bytes + 65_536:
        raise ValueError("benchmark audio has unexpected trailing data")
    if size_bytes > 2_000_000:
        raise ValueError("benchmark audio exceeds the 60-second memory boundary")
    return BenchmarkWav(
        path=path,
        size_bytes=size_bytes,
        duration_seconds=frames / sample_rate,
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
    )


def snapshot_bounded_regular_file(source: Path, destination: Path, *, max_bytes: int) -> None:
    """Copy a regular non-symlink input through an opened descriptor with a hard size cap."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise ValueError("input must be a readable regular file") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= max_bytes:
            raise ValueError("input file exceeds the allowed size boundary")
        with (
            os.fdopen(descriptor, "rb", closefd=False) as input_file,
            destination.open("xb") as output_file,
        ):
            copied = 0
            while chunk := input_file.read(min(1024 * 1024, max_bytes - copied + 1)):
                copied += len(chunk)
                if copied > max_bytes:
                    raise ValueError("input file exceeds the allowed size boundary")
                output_file.write(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
        if copied != metadata.st_size:
            raise ValueError("input file changed while it was being snapshotted")
    finally:
        os.close(descriptor)


def build_browser_worker_command(
    *,
    node_bin: str,
    worker: Path,
    renderer_url: str,
    audio: Path,
    control_audio: Path,
    raw_video: Path,
    evidence: Path,
    duration_seconds: float,
    canvas_width: int = 720,
    canvas_height: int = 1080,
) -> list[str]:
    """Build a loopback-only Playwright worker invocation without a shell."""

    parsed_url = urlsplit(renderer_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("renderer URL must use loopback HTTP")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and positive")
    if duration_seconds > 60:
        raise ValueError("browser benchmark duration cannot exceed 60 seconds")
    if (
        type(canvas_width) is not int
        or type(canvas_height) is not int
        or not 1 <= canvas_width <= 4096
        or not 1 <= canvas_height <= 4096
    ):
        raise ValueError("canvas dimensions must be integers between 1 and 4096")
    duration_ms = round(duration_seconds * 1000)
    return [
        node_bin,
        str(worker),
        "--renderer-url",
        renderer_url,
        "--audio",
        str(audio),
        "--control-audio",
        str(control_audio),
        "--raw-video",
        str(raw_video),
        "--evidence",
        str(evidence),
        "--duration-ms",
        str(duration_ms),
        "--canvas-width",
        str(canvas_width),
        "--canvas-height",
        str(canvas_height),
    ]


def validate_browser_benchmark_evidence(
    evidence: BrowserBenchmarkEvidence,
    expected_audio_bytes: int,
    expected_duration_seconds: float,
    expected_control_audio_bytes: int | None = None,
    expected_canvas_width: int = 720,
    expected_canvas_height: int = 1080,
) -> BrowserBenchmarkMetrics:
    """Prove speech response exceeds a same-duration silence-control envelope."""

    if (
        evidence.canvas_width != expected_canvas_width
        or evidence.canvas_height != expected_canvas_height
    ):
        raise ValueError("unexpected DH_live canvas dimensions")
    if evidence.set_audio_buffer_calls != 2:
        raise ValueError("speech and silence-control audio buffers were not both submitted")
    control_bytes = (
        expected_audio_bytes
        if expected_control_audio_bytes is None
        else expected_control_audio_bytes
    )
    if (
        evidence.speech_audio_bytes != expected_audio_bytes
        or evidence.control_audio_bytes != control_bytes
    ):
        raise ValueError("audio byte count does not match the benchmark input")
    if "webgl 2" not in evidence.webgl_version.lower():
        raise ValueError("WebGL2 renderer is required")
    if not evidence.browser_version.strip():
        raise ValueError("browser version is missing")
    if not math.isfinite(expected_duration_seconds) or expected_duration_seconds <= 0:
        raise ValueError("expected duration must be finite and positive")
    for label, timestamps, deltas in (
        ("control", evidence.control_timestamps_ms, evidence.control_blend_shape_deltas),
        ("speech", evidence.speech_timestamps_ms, evidence.speech_blend_shape_deltas),
    ):
        if len(timestamps) < 3 or len(timestamps) != len(deltas):
            raise ValueError(f"{label} requires matching renderer samples")
        if any(not math.isfinite(value) for value in (*timestamps, *deltas)):
            raise ValueError(f"{label} samples must be finite")
        if any(value < 0 for value in (*timestamps, *deltas)):
            raise ValueError(f"{label} samples must be non-negative")
        if any(right <= left for left, right in pairwise(timestamps)):
            raise ValueError("frame timestamps must be strictly monotonic")
        expected_duration_ms = expected_duration_seconds * 1000
        if timestamps[0] > 120 or timestamps[-1] < expected_duration_ms - 120:
            raise ValueError(f"{label} samples do not cover the full audio duration")
        if timestamps[-1] > expected_duration_ms + 120:
            raise ValueError(f"{label} samples exceed the audio duration")
        if max(right - left for left, right in pairwise(timestamps)) > 120:
            raise ValueError(f"{label} renderer samples contain an excessive gap")
        if len(timestamps) < math.floor(expected_duration_seconds * 20):
            raise ValueError(f"{label} renderer sample count is too low")

    silence_max = max(evidence.control_blend_shape_deltas)
    threshold = max(0.05, silence_max * 3)
    significant_indices = [
        index for index, delta in enumerate(evidence.speech_blend_shape_deltas) if delta > threshold
    ]
    if len(significant_indices) < 3:
        raise ValueError("speech response does not exceed the silence baseline")

    timestamps = evidence.speech_timestamps_ms
    average_fps = _fps(timestamps)
    midpoint = timestamps[0] + (timestamps[-1] - timestamps[0]) / 2
    second_half = tuple(value for value in timestamps if value >= midpoint)
    if len(second_half) < 2:
        raise ValueError("second-half frame timestamps are insufficient")
    return BrowserBenchmarkMetrics(
        renderer_update_samples=len(timestamps),
        average_fps=average_fps,
        second_half_fps=_fps(second_half),
        first_audio_driven_blend_change_ms=timestamps[significant_indices[0]],
        silence_calibrated_threshold=threshold,
        silence_max_delta=silence_max,
        speech_max_delta=max(evidence.speech_blend_shape_deltas),
        significant_speech_samples=len(significant_indices),
        playback_observation_seconds=(timestamps[-1] - timestamps[0]) / 1000,
    )


def _fps(timestamps_ms: tuple[float, ...]) -> float:
    return (len(timestamps_ms) - 1) * 1000 / (timestamps_ms[-1] - timestamps_ms[0])


def build_dh_live_normalize_command(
    *,
    raw_video: Path,
    audio: Path,
    output: Path,
    duration_seconds: float,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    """Build the normalization and exact-input mux command without a shell."""

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
        "fps=25,scale=720:1080:flags=lanczos,pad=720:1280:0:100:black,tpad=stop_mode=clone:stop_duration=0.200,format=yuv420p",
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required executable is missing: {name}")
    return executable


def _run(
    command: list[str],
    *,
    capture_output: bool = False,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=capture_output,
            check=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Command timed out after {timeout}s: {command[0]}") from error


def probe_normalized_video(
    path: Path,
    *,
    ffprobe_bin: str,
    expected_duration_seconds: float | None = None,
) -> NormalizedVideo:
    result = _run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,sample_rate,duration,channels:format=duration,size",
            "-count_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        audio = next(stream for stream in streams if stream["codec_type"] == "audio")
        normalized = NormalizedVideo(
            duration_seconds=float(payload["format"]["duration"]),
            size_bytes=int(payload["format"]["size"]),
            video_codec=str(video["codec_name"]),
            audio_codec=str(audio["codec_name"]),
            width=int(video["width"]),
            height=int(video["height"]),
            frame_rate=_parse_frame_rate(str(video["r_frame_rate"])),
            video_frame_count=int(video["nb_read_frames"]),
            audio_sample_rate_hz=int(audio["sample_rate"]),
            video_duration_seconds=float(video["duration"]),
            audio_duration_seconds=float(audio["duration"]),
            audio_channels=int(audio["channels"]),
        )
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("normalized DH_live artifact has invalid ffprobe output") from error
    if (
        normalized.video_codec != "h264"
        or normalized.audio_codec != "aac"
        or normalized.width != 720
        or normalized.height != 1280
        or not math.isfinite(normalized.frame_rate)
        or abs(normalized.frame_rate - 25) > 0.01
        or normalized.video_frame_count <= 0
        or normalized.audio_sample_rate_hz != 24_000
        or normalized.audio_channels != 1
        or not math.isfinite(normalized.video_duration_seconds)
        or not math.isfinite(normalized.audio_duration_seconds)
        or not math.isfinite(normalized.duration_seconds)
        or normalized.duration_seconds <= 0
        or normalized.size_bytes <= 0
    ):
        raise ValueError("normalized DH_live artifact does not match the media contract")
    if expected_duration_seconds is not None:
        expected_frames = round(expected_duration_seconds * 25)
        if (
            abs(normalized.video_frame_count - expected_frames) > 1
            or abs(normalized.video_duration_seconds - expected_duration_seconds) > 0.08
            or abs(normalized.audio_duration_seconds - expected_duration_seconds) > 0.08
        ):
            raise ValueError("normalized DH_live streams do not cover the benchmark duration")
    return normalized


def _parse_frame_rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    denominator_value = float(denominator)
    if denominator_value == 0:
        raise ValueError("frame-rate denominator cannot be zero")
    return float(numerator) / denominator_value


def publish_file_no_replace(staged: Path, destination: Path) -> None:
    """Atomically publish on the same filesystem without replacing a concurrent result."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(staged, destination)
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def publish_benchmark_files(
    *,
    staged_video: Path,
    staged_evidence: Path,
    output_path: Path,
    evidence_path: Path,
    append_record: Callable[[], None],
) -> None:
    """Publish both artifacts and roll them back if canonical registration fails."""

    published: list[Path] = []
    try:
        publish_file_no_replace(staged_video, output_path)
        published.append(output_path)
        publish_file_no_replace(staged_evidence, evidence_path)
        published.append(evidence_path)
        append_record()
    except BaseException:
        for published_path in reversed(published):
            published_path.unlink(missing_ok=True)
        raise


def _write_silence_wav(path: Path, wav: BenchmarkWav) -> None:
    frame_count = round(wav.duration_seconds * wav.sample_rate_hz)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(wav.channels)
        output.setsampwidth(wav.sample_width_bytes)
        output.setframerate(wav.sample_rate_hz)
        output.writeframes(b"\0" * frame_count * wav.channels * wav.sample_width_bytes)


def _write_json_staged(path: Path, payload: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def run_dh_live_benchmark(
    *,
    runtime_root: Path,
    campaign: Path,
    audio_path: Path,
    output_path: Path,
    run_id: str,
    rights_confirmed: bool,
) -> dict[str, object]:
    """Execute the isolated renderer, normalize its capture, and record canonical metrics."""

    if rights_confirmed is not True:
        raise ValueError("Audio and avatar evaluation rights must be confirmed")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", run_id):
        raise ValueError("run_id must contain only lowercase letters, numbers, and hyphens")
    campaign = campaign.resolve()
    output_path = output_path.resolve()
    runs_root = campaign / "runs"
    if not output_path.is_relative_to(runs_root):
        raise ValueError("DH_live benchmark output must stay inside the campaign runs directory")
    if output_path.stem != run_id:
        raise ValueError("output filename must match run_id")
    audio_path = audio_path.resolve()
    if not audio_path.is_relative_to(campaign):
        raise ValueError("benchmark audio must stay inside the campaign directory")
    input_relative = audio_path.relative_to(campaign).as_posix()
    if output_path.exists():
        raise FileExistsError(output_path)
    evidence_path = output_path.with_suffix(".evidence.json")
    if evidence_path.exists():
        raise FileExistsError(evidence_path)

    runtime = DHLiveRuntime(runtime_root.resolve() / "repository", Path(sys.executable).resolve())
    diagnostic = inspect_dh_live_runtime(runtime)
    if not diagnostic.ready:
        raise RuntimeError("DH_live runtime is not ready: " + "; ".join(diagnostic.issues))
    benchmark_path = campaign / "benchmark.csv"
    if not benchmark_path.is_file():
        raise FileNotFoundError(benchmark_path)
    node_bin = _required_executable("node")
    ffmpeg_bin = _required_executable("ffmpeg")
    ffprobe_bin = _required_executable("ffprobe")
    worker = Path(__file__).with_name("dh_live_browser_worker.mjs")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".dh-live-benchmark-",
        dir=output_path.parent,
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

        server = create_dh_live_server(
            runtime,
            port=0,
            usage_scope="internal_evaluation",
            allow_ephemeral=True,
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        renderer_url = f"http://127.0.0.1:{server.server_port}/MiniLive.html"
        try:
            _run(
                build_browser_worker_command(
                    node_bin=node_bin,
                    worker=worker,
                    renderer_url=renderer_url,
                    audio=audio_snapshot,
                    control_audio=control_audio,
                    raw_video=raw_video,
                    evidence=raw_evidence,
                    duration_seconds=wav.duration_seconds,
                ),
                timeout=60,
            )
            browser_evidence = load_browser_benchmark_evidence(raw_evidence)
            metrics = validate_browser_benchmark_evidence(
                browser_evidence,
                expected_audio_bytes=wav.size_bytes,
                expected_control_audio_bytes=control_wav.size_bytes,
                expected_duration_seconds=wav.duration_seconds,
            )
            playback_observation_seconds = metrics.playback_observation_seconds
            _run(
                build_dh_live_normalize_command(
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
            if abs(normalized.duration_seconds - wav.duration_seconds) > 0.15:
                raise ValueError("normalized DH_live duration does not match the benchmark audio")
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        recorded_at = datetime.now(UTC).isoformat()
        output_relative = output_path.relative_to(campaign).as_posix()
        artifact_sha256 = _sha256(normalized_video)
        evidence_payload = {
            "schema_version": 2,
            "run_id": run_id,
            "provider": "dh-live-mini",
            "recorded_at": recorded_at,
            "runtime_commit": DH_LIVE_COMMIT,
            "official_sample_frames": diagnostic.sample_frames,
            "avatar_scope": "official-prebuilt-sample-not-campaign-portrait",
            "input": {
                "path": input_relative,
                "size_bytes": wav.size_bytes,
                "sha256": input_sha256,
                "duration_seconds": wav.duration_seconds,
                "sample_rate_hz": wav.sample_rate_hz,
                "channels": wav.channels,
                "sample_width_bytes": wav.sample_width_bytes,
            },
            "browser": asdict(browser_evidence),
            "metrics": asdict(metrics),
            "metric_semantics": {
                "first_audio_driven_blend_change_ms": (
                    "First speech blend-shape delta above 3x the same-duration silence envelope; "
                    "not a visible canvas frame or end-to-end latency."
                ),
                "playback_observation_seconds": (
                    "Paced browser observation window; not model compute time or comparable RTF."
                ),
            },
            "artifact": {
                "path": output_relative,
                "size_bytes": normalized.size_bytes,
                "sha256": artifact_sha256,
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
                "Official prebuilt sample avatar, not the campaign portrait.",
                "Visible MatesX watermark; internal evaluation only.",
                "Short-run browser benchmark; AV drift, interruption, and 10-minute stability remain unmeasured.",
                "Repository and avatar commercial licensing remain unresolved.",
            ],
        }
        _write_json_staged(staged_evidence, evidence_payload)
        notes = (
            "Apple M1 browser WASM/WebGL2 internal evaluation; silence-calibrated speech "
            "blend-shape response; official watermarked sample avatar only, not campaign portrait; "
            f"input_sha256={input_sha256}; browser_evidence="
            f"{evidence_path.relative_to(campaign).as_posix()}; playback window is not compute RTF; "
            "AV drift, interruption P95, 10-minute stability, custom avatar, and license pending"
        )
        record = BenchmarkRecord(
            run_id=run_id,
            provider="dh-live-mini",
            artifact_id=run_id,
            mode="realtime",
            status="experimental",
            recorded_at=recorded_at,
            duration_seconds=wav.duration_seconds,
            render_seconds=playback_observation_seconds,
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path("models/dh_live"))
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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    payload = run_dh_live_benchmark(
        runtime_root=args.runtime_root,
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
