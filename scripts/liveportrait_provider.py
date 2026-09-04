"""Thin, reproducible wrapper around the official LivePortrait CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

LIVEPORTRAIT_REPOSITORY_URL = "https://github.com/KlingAIResearch/LivePortrait.git"
LIVEPORTRAIT_COMMIT = "9b294b3d0536135442ea73cb01e6cb3ca7029dd3"
LIVEPORTRAIT_MODEL_REVISION = "82a4fa6735ca58432b6ce39301b4b9ee066dea47"
REQUIRED_PYTHON = (3, 10, 20)
PROBE_TIMEOUT_SECONDS = 60

HUMAN_WEIGHT_FILES = {
    Path("insightface/models/buffalo_l/2d106det.onnx"): 5_030_888,
    Path("insightface/models/buffalo_l/det_10g.onnx"): 16_923_827,
    Path("liveportrait/base_models/appearance_feature_extractor.pth"): 3_387_959,
    Path("liveportrait/base_models/motion_extractor.pth"): 112_545_506,
    Path("liveportrait/base_models/spade_generator.pth"): 221_813_590,
    Path("liveportrait/base_models/warping_module.pth"): 182_180_086,
    Path("liveportrait/landmark.onnx"): 114_666_491,
    Path("liveportrait/retargeting_models/stitching_retargeting_module.pth"): 2_393_098,
}
HUMAN_WEIGHT_HASHES = {
    Path("insightface/models/buffalo_l/2d106det.onnx"): (
        "f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf"
    ),
    Path("insightface/models/buffalo_l/det_10g.onnx"): (
        "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"
    ),
    Path("liveportrait/base_models/appearance_feature_extractor.pth"): (
        "5279bb8654293dbdf327030b397f107237dd9212fb11dd75b83dfb635211ceb5"
    ),
    Path("liveportrait/base_models/motion_extractor.pth"): (
        "251e6a94ad667a1d0c69526d292677165110ef7f0cf0f6d199f0e414e8aa0ca5"
    ),
    Path("liveportrait/base_models/spade_generator.pth"): (
        "4780afc7909a9f84e24c01d73b31a555ef651521a1fe3b2429bd04534d992aee"
    ),
    Path("liveportrait/base_models/warping_module.pth"): (
        "2f61a6f265fe344f14132364859a78bdbbc2068577170693da57fb96d636e282"
    ),
    Path("liveportrait/landmark.onnx"): (
        "31d22a5041326c31f19b78886939a634a5aedcaa5ab8b9b951a1167595d147db"
    ),
    Path("liveportrait/retargeting_models/stitching_retargeting_module.pth"): (
        "3652d5a3f95099141a56986aaddec92fadf0a73c87a20fac9a2c07c32b28b611"
    ),
}


@dataclass(frozen=True)
class LivePortraitRuntime:
    """Paths to an isolated checkout and Python environment."""

    repository: Path
    python: Path


@dataclass(frozen=True)
class LivePortraitRenderSpec:
    """One rights-gated portrait animation request."""

    source: Path
    driving: Path
    output_dir: Path
    rights_confirmed: bool
    runtime_config: dict[str, object] | None = None


@dataclass(frozen=True)
class LivePortraitRuntimeDiagnostic:
    """Observed readiness of an isolated LivePortrait runtime."""

    ready: bool
    device: str
    weights_bytes: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class LivePortraitRenderResult:
    """Observed output of one official CLI invocation."""

    output_path: Path
    render_seconds: float


@dataclass(frozen=True)
class DrivingMouthInspection:
    """Closed-mouth suitability derived from sampled LivePortrait landmarks."""

    eligible: bool
    reason: str | None
    sample_count: int
    median_ratio: float
    maximum_ratio: float


@dataclass(frozen=True)
class DrivingVideoInspection:
    """Server-authoritative duration and closed-mouth gate for uploaded driving media."""

    eligible: bool
    reason: str | None
    duration_seconds: float
    sample_count: int
    median_ratio: float
    maximum_ratio: float


def classify_driving_mouth_motion(ratios: list[float]) -> DrivingMouthInspection:
    """Classify the sampled official lip-close ratios for a driving performance."""

    if not ratios:
        return DrivingMouthInspection(False, "未检测到可用的人脸嘴部特征", 0, 0.0, 0.0)
    values = [float(value) for value in ratios]
    median_ratio = statistics.median(values)
    maximum_ratio = max(values)
    if median_ratio >= 0.02:
        return DrivingMouthInspection(
            False,
            "参考视频中嘴部持续张开，请改用自然闭嘴的非语言表演",
            len(values),
            median_ratio,
            maximum_ratio,
        )
    sorted_values = sorted(values)
    baseline_count = max(1, len(sorted_values) // 4)
    closed_baseline = statistics.median(sorted_values[:baseline_count])
    moving_open_frames = sum(value >= closed_baseline + 0.025 for value in values)
    if maximum_ratio >= 0.12 or (
        maximum_ratio - closed_baseline >= 0.035
        and moving_open_frames / len(values) >= 0.20
    ):
        return DrivingMouthInspection(
            False,
            "参考视频包含明显说话口型或大幅嘴部运动，请重新录制闭嘴表演",
            len(values),
            median_ratio,
            maximum_ratio,
        )
    return DrivingMouthInspection(
        eligible=True,
        reason=None,
        sample_count=len(values),
        median_ratio=median_ratio,
        maximum_ratio=maximum_ratio,
    )


def inspect_driving_video(
    runtime: LivePortraitRuntime,
    driving: Path,
    *,
    ffprobe: Path,
    analyzer_script: Path | None = None,
) -> DrivingVideoInspection:
    """Inspect an uploaded driving video before any LivePortrait render is queued."""

    probe = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration:format=duration",
            "-of",
            "json",
            str(driving),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    payload = json.loads(probe.stdout)
    streams = payload.get("streams", [])
    stream_duration = streams[0].get("duration") if streams else None
    duration = float(stream_duration or payload.get("format", {}).get("duration") or 0)
    if duration < 5 or duration > 15:
        return DrivingVideoInspection(
            False,
            "自定义参考视频需为 5–15 秒",
            duration,
            0,
            0.0,
            0.0,
        )
    analyzer = analyzer_script or Path(__file__).with_name("liveportrait_inspect_driving.py")
    analysis = subprocess.run(
        [
            str(runtime.python),
            str(analyzer),
            "--video",
            str(driving),
            "--repository",
            str(runtime.repository),
            "--samples",
            "24",
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS * 3,
    )
    analysis_payload = json.loads(analysis.stdout)
    ratios = analysis_payload.get("ratios")
    if not isinstance(ratios, list) or not all(isinstance(value, (int, float)) for value in ratios):
        raise RuntimeError("LivePortrait driving analyzer returned invalid ratios")
    attempted_samples = analysis_payload.get("attempted_samples")
    detected_samples = analysis_payload.get("detected_samples")
    if not isinstance(attempted_samples, int) or not isinstance(detected_samples, int):
        raise RuntimeError("LivePortrait driving analyzer returned invalid coverage")
    if attempted_samples < 1 or detected_samples < 4 or detected_samples / attempted_samples < 0.75:
        return DrivingVideoInspection(
            False,
            "参考视频中未持续检测到清晰单人脸，请重新录制",
            duration,
            len(ratios),
            statistics.median(ratios) if ratios else 0.0,
            max(ratios) if ratios else 0.0,
        )
    mouth = classify_driving_mouth_motion([float(value) for value in ratios])
    return DrivingVideoInspection(
        mouth.eligible,
        mouth.reason,
        duration,
        mouth.sample_count,
        mouth.median_ratio,
        mouth.maximum_ratio,
    )


def build_liveportrait_render_command(
    runtime: LivePortraitRuntime,
    spec: LivePortraitRenderSpec,
) -> list[str]:
    """Build the official inference command without executing it."""

    if not spec.rights_confirmed:
        raise ValueError("Source and driving-media rights must be confirmed")
    command = [
        str(runtime.python),
        str(runtime.repository / "inference.py"),
        "-s",
        str(spec.source),
        "-d",
        str(spec.driving),
        "-o",
        str(spec.output_dir),
    ]
    runtime_config = spec.runtime_config or {}
    if "driving_multiplier" in runtime_config:
        command.extend(["--driving-multiplier", str(runtime_config["driving_multiplier"])])
    if "animation_region" in runtime_config:
        command.extend(["--animation-region", str(runtime_config["animation_region"])])
    for key in (
        "flag_stitching",
        "flag_pasteback",
        "flag_normalize_lip",
        "flag_relative_motion",
    ):
        if key not in runtime_config:
            continue
        cli_name = key.replace("_", "-")
        command.append(f"--{cli_name}" if runtime_config[key] is True else f"--no-{cli_name}")
    return command


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_repository(repository: Path) -> list[str]:
    issues: list[str] = []
    git = shutil.which("git")
    if not git:
        return ["missing Git executable"]
    if not (repository / ".git").is_dir():
        return [f"official repository is not a Git checkout: {repository}"]
    try:
        origin = subprocess.run(
            [git, "-C", str(repository), "remote", "get-url", "origin"],
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.strip()
        commit = subprocess.run(
            [git, "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.strip()
        status_lines = subprocess.run(
            [git, "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ["official repository Git verification failed"]
    if origin != LIVEPORTRAIT_REPOSITORY_URL:
        issues.append(f"unexpected repository origin: {origin}")
    if commit != LIVEPORTRAIT_COMMIT:
        issues.append(f"unexpected repository commit: {commit}")

    allowed_weights = {
        (Path("pretrained_weights") / relative_path).as_posix()
        for relative_path in HUMAN_WEIGHT_FILES
    }
    for line in status_lines:
        status, changed_path = line[:2], line[3:]
        if status == "??" and changed_path in allowed_weights:
            continue
        issues.append(f"repository has unexpected change: {line}")
    return issues


def inspect_liveportrait_runtime(
    runtime: LivePortraitRuntime,
    *,
    ffmpeg: Path,
) -> LivePortraitRuntimeDiagnostic:
    """Verify source, weights, runtime version, imports, and accelerator."""

    issues: list[str] = []
    if not runtime.python.is_file():
        issues.append(f"missing Python executable: {runtime.python}")
    inference_script = runtime.repository / "inference.py"
    if not inference_script.is_file():
        issues.append(f"missing official inference script: {inference_script}")
    if not ffmpeg.is_file():
        issues.append(f"missing FFmpeg executable: {ffmpeg}")
    if runtime.repository.exists():
        issues.extend(_inspect_repository(runtime.repository))

    weights_root = runtime.repository / "pretrained_weights"
    for relative_path, expected_size in HUMAN_WEIGHT_FILES.items():
        weight_path = weights_root / relative_path
        if not weight_path.is_file():
            issues.append(f"missing weight: {relative_path.as_posix()}")
        elif weight_path.stat().st_size != expected_size:
            issues.append(f"invalid weight size: {relative_path.as_posix()}")
        elif _sha256(weight_path) != HUMAN_WEIGHT_HASHES[relative_path]:
            issues.append(f"invalid weight hash: {relative_path.as_posix()}")

    device = "unknown"
    if runtime.python.is_file():
        try:
            probe = subprocess.run(
                [
                    str(runtime.python),
                    "-c",
                    (
                        "import json, sys, torch; "
                        "device = ('mps' if torch.backends.mps.is_available() else "
                        "'cuda' if torch.cuda.is_available() else 'cpu'); "
                        "print(json.dumps({'device': device, "
                        "'python': list(sys.version_info[:3])}))"
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            issues.append("Python device probe timed out")
        else:
            if probe.returncode == 0:
                try:
                    payload = json.loads(probe.stdout)
                    device = str(payload["device"])
                    version = tuple(int(part) for part in payload["python"])
                    if version != tuple(REQUIRED_PYTHON):
                        issues.append(f"unexpected Python version: {version}")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    issues.append("Python device probe returned invalid JSON")
            else:
                issues.append("Python runtime cannot import torch")

    integrity_verified = not issues
    if integrity_verified:
        try:
            cli_probe = subprocess.run(
                [str(runtime.python), str(inference_script), "--help"],
                capture_output=True,
                check=False,
                cwd=runtime.repository,
                env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            issues.append("official LivePortrait CLI import probe timed out")
        else:
            if cli_probe.returncode != 0:
                issues.append("official LivePortrait CLI import probe failed")

    return LivePortraitRuntimeDiagnostic(
        ready=not issues,
        device=device,
        weights_bytes=sum(HUMAN_WEIGHT_FILES.values()),
        issues=tuple(issues),
    )


def _verify_video(ffprobe: Path, output_path: Path) -> None:
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"LivePortrait output is missing or empty: {output_path}")
    probe = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,nb_frames",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"LivePortrait output has no video stream: {output_path}")
    stream = streams[0]
    duration = float(stream.get("duration") or 0)
    frames = int(stream.get("nb_frames") or 0)
    if duration <= 0 and frames <= 0:
        raise RuntimeError(f"LivePortrait output has no frames or duration: {output_path}")


def _publish_file_no_replace(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError:
        raise FileExistsError(destination) from None
    source.unlink()


def run_liveportrait_render(
    runtime: LivePortraitRuntime,
    spec: LivePortraitRenderSpec,
    *,
    ffmpeg: Path,
    ffprobe: Path,
    timeout_seconds: float = 900,
) -> LivePortraitRenderResult:
    """Verify the runtime, render to a temporary directory, then promote atomically."""

    if not spec.source.is_file():
        raise FileNotFoundError(spec.source)
    if not spec.driving.is_file():
        raise FileNotFoundError(spec.driving)
    diagnostic = inspect_liveportrait_runtime(runtime, ffmpeg=ffmpeg)
    if not diagnostic.ready:
        raise RuntimeError("LivePortrait runtime is not ready: " + "; ".join(diagnostic.issues))

    resolved_spec = LivePortraitRenderSpec(
        source=spec.source.resolve(),
        driving=spec.driving.resolve(),
        output_dir=spec.output_dir.resolve(),
        rights_confirmed=spec.rights_confirmed,
        runtime_config=spec.runtime_config,
    )
    output_name = f"{resolved_spec.source.stem}--{resolved_spec.driving.stem}.mp4"
    output_path = resolved_spec.output_dir / output_name
    if output_path.exists():
        raise FileExistsError(output_path)
    resolved_spec.output_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = resolved_spec.output_dir / f".liveportrait.{uuid.uuid4().hex}.partial"
    staged_inputs = temporary_dir / "inputs"
    staged_output = temporary_dir / "output"
    staged_inputs.mkdir(parents=True)
    staged_source = staged_inputs / f"source{resolved_spec.source.suffix.lower()}"
    staged_driving = staged_inputs / f"driving{resolved_spec.driving.suffix.lower()}"
    shutil.copyfile(resolved_spec.source, staged_source)
    shutil.copyfile(resolved_spec.driving, staged_driving)
    temporary_spec = LivePortraitRenderSpec(
        source=staged_source,
        driving=staged_driving,
        output_dir=staged_output,
        rights_confirmed=resolved_spec.rights_confirmed,
        runtime_config=resolved_spec.runtime_config,
    )
    temporary_output = staged_output / (f"{staged_source.stem}--{staged_driving.stem}.mp4")

    started_at = time.perf_counter()
    try:
        subprocess.run(
            build_liveportrait_render_command(runtime, temporary_spec),
            check=True,
            cwd=runtime.repository,
            env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
            timeout=timeout_seconds,
        )
        render_seconds = time.perf_counter() - started_at
        _verify_video(ffprobe, temporary_output)
        _publish_file_no_replace(temporary_output, output_path)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return LivePortraitRenderResult(output_path=output_path, render_seconds=render_seconds)


def _runtime_from_root(runtime_root: Path) -> LivePortraitRuntime:
    runtime_root = runtime_root.resolve()
    return LivePortraitRuntime(
        repository=runtime_root / "repository",
        python=runtime_root / ".venv/bin/python",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose = subparsers.add_parser("diagnose", help="inspect an isolated runtime")
    diagnose.add_argument("--runtime-root", type=Path, default=Path("models/liveportrait"))
    render = subparsers.add_parser("render", help="render one rights-confirmed motion base")
    render.add_argument("source", type=Path)
    render.add_argument("driving", type=Path)
    render.add_argument("output_dir", type=Path)
    render.add_argument("--runtime-root", type=Path, default=Path("models/liveportrait"))
    render.add_argument("--rights-confirmed", action="store_true")
    render.add_argument("--timeout-seconds", type=float, default=900)
    render.add_argument("--config-json", type=Path)
    inspect_driving = subparsers.add_parser(
        "inspect-driving", help="validate uploaded driving duration and closed-mouth motion"
    )
    inspect_driving.add_argument("driving", type=Path)
    inspect_driving.add_argument("--runtime-root", type=Path, default=Path("models/liveportrait"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    ffmpeg_value = shutil.which("ffmpeg")
    ffprobe_value = shutil.which("ffprobe")
    ffmpeg = Path(ffmpeg_value) if ffmpeg_value else Path("/missing/ffmpeg")
    ffprobe = Path(ffprobe_value) if ffprobe_value else Path("/missing/ffprobe")
    runtime = _runtime_from_root(args.runtime_root)
    if args.command == "diagnose":
        diagnostic = inspect_liveportrait_runtime(runtime, ffmpeg=ffmpeg)
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    if args.command == "inspect-driving":
        inspection = inspect_driving_video(runtime, args.driving, ffprobe=ffprobe)
        print(json.dumps(asdict(inspection), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "render":
        runtime_config = None
        if args.config_json is not None:
            if not args.config_json.is_file() or args.config_json.stat().st_size > 64 * 1024:
                raise ValueError("invalid FasterLivePortrait config snapshot")
            runtime_config = json.loads(args.config_json.read_text(encoding="utf-8"))
            if not isinstance(runtime_config, dict):
                raise ValueError("FasterLivePortrait config snapshot must be an object")
        result = run_liveportrait_render(
            runtime,
            LivePortraitRenderSpec(
                source=args.source,
                driving=args.driving,
                output_dir=args.output_dir,
                rights_confirmed=args.rights_confirmed,
                runtime_config=runtime_config,
            ),
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            timeout_seconds=args.timeout_seconds,
        )
        diagnostic = inspect_liveportrait_runtime(runtime, ffmpeg=ffmpeg)
        print(
            json.dumps(
                {
                    "device": diagnostic.device,
                    "output": str(result.output_path),
                    "render_seconds": result.render_seconds,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
