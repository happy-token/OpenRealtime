"""Verified local LiteAvatar CPU offline renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

LITEAVATAR_REPOSITORY_URL = "https://github.com/HumanAIGC/lite-avatar.git"
LITEAVATAR_COMMIT = "5b7ec850945e03d56fb290b05fb68440c359fa86"
LITEAVATAR_PATCH_DIFF_SHA256 = "e97be206764623ca9c16f943f0b22e2e93a845fbfc80479f36d2f01419d78d6d"
REQUIRED_PYTHON = (3, 10, 20)
PROBE_TIMEOUT_SECONDS = 90
ALLOWED_USAGE_SCOPES = {"internal_evaluation", "research"}
LITEAVATAR_WEIGHT_FILES = {
    Path("weights/model_1.onnx"): 184_415_825,
    Path(
        "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/model.pb"
    ): 880_502_012,
    Path(
        "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/lm/lm.pb"
    ): 237_373_385,
}
LITEAVATAR_WEIGHT_HASHES = {
    Path(
        "weights/model_1.onnx"
    ): "312f0213a23a1c17ecb66f9edf8413b8ef193c0d4d2f5f9dd6714a178492c34c",
    Path(
        "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/model.pb"
    ): "5bba782a5e9196166233b9ab12ba04cadff9ef9212b4ff6153ed9290ff679025",
    Path(
        "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/lm/lm.pb"
    ): "5b59db5f607fde57bd8d6c8df8f22ce5b37ec7adcdb7b4ee785a4478f06c1c50",
}
LITEAVATAR_SAMPLE_HASHES = {
    "bg_video.mp4": "72fc5d242d7fd7837335d5b76d0e3df9250305ae281249404af7a8b206c0857f",
    "face_box.txt": "26e4ab5a60ce12295009961b45082a59e1117312583cda1adefc868a62681e06",
    "net_decode.pt": "d1e799cd63d3804b6448054c930c9afc8b9c79fa38ed525ea9c6ca1ada512898",
    "net_encode.pt": "035e7ae58485d3b62053f6f237532a6e5d1347cf203bdb9a4821260bac0fd46e",
    "net.pth": "2bcdf689d20c9b5ef56c1e3fe2d641a1d8f661c6283cf5ce265e7ec721e9ad74",
    "neutral_pose.npy": "facde273385a4027b6db1fb9cbd76bb911480d2a3a9b9735ce40f8cdf3eaebab",
}
LITEAVATAR_REFERENCE_FRAMES_SHA256 = (
    "cfc533a20fca8af08e10d9df7ca4a2970b2368dee984e93133380a2adc3184f6"
)


@dataclass(frozen=True)
class LiteAvatarRuntime:
    repository: Path
    python: Path


@dataclass(frozen=True)
class LiteAvatarRenderSpec:
    audio: Path
    avatar_dir: Path
    output: Path
    rights_confirmed: bool
    usage_scope: str = "internal_evaluation"


@dataclass(frozen=True)
class LiteAvatarDiagnostic:
    ready: bool
    device: str
    weights_bytes: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class LiteAvatarRenderResult:
    output_path: Path
    render_seconds: float


def build_liteavatar_render_command(
    runtime: LiteAvatarRuntime,
    spec: LiteAvatarRenderSpec,
    *,
    result_dir: Path,
) -> list[str]:
    if not spec.rights_confirmed:
        raise ValueError("Audio and avatar rights must be confirmed")
    if spec.usage_scope not in ALLOWED_USAGE_SCOPES:
        raise ValueError("LiteAvatar model weights have no explicit commercial license")
    official_avatar = (runtime.repository / "data/sample_data/preload").resolve()
    if spec.avatar_dir.resolve() != official_avatar:
        raise ValueError("LiteAvatar only permits the hash-verified official sample avatar")
    if spec.audio.suffix.lower() != ".wav":
        raise ValueError("LiteAvatar requires a 16 kHz mono WAV input")
    return [
        str(runtime.python),
        str(runtime.repository / "lite_avatar.py"),
        "--data_dir",
        str(spec.avatar_dir.resolve()),
        "--audio_file",
        str(spec.audio.resolve()),
        "--result_dir",
        str(result_dir.resolve()),
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_repository(repository: Path) -> list[str]:
    git = shutil.which("git")
    if not git or not (repository / ".git").is_dir():
        return [f"LiteAvatar source is not a Git checkout: {repository}"]
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
        diff = subprocess.run(
            [git, "-C", str(repository), "diff", "--binary", "HEAD"],
            capture_output=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout
        status_lines = subprocess.run(
            [git, "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ["LiteAvatar Git verification failed"]
    issues: list[str] = []
    if origin != LITEAVATAR_REPOSITORY_URL:
        issues.append(f"unexpected repository origin: {origin}")
    if commit != LITEAVATAR_COMMIT:
        issues.append(f"unexpected repository commit: {commit}")
    if hashlib.sha256(diff).hexdigest() != LITEAVATAR_PATCH_DIFF_SHA256:
        issues.append("LiteAvatar compatibility patch hash mismatch")
    allowed = {path.as_posix() for path in LITEAVATAR_WEIGHT_FILES}
    allowed.update(f"data/sample_data/preload/{name}" for name in LITEAVATAR_SAMPLE_HASHES)
    allowed.update(
        f"data/sample_data/preload/ref_frames/ref_{index:05d}.jpg" for index in range(150)
    )
    for line in status_lines:
        if line.startswith("?? ") and line[3:] not in allowed:
            issues.append(f"repository has unexpected untracked file: {line[3:]}")
    return issues


def inspect_liteavatar_runtime(runtime: LiteAvatarRuntime) -> LiteAvatarDiagnostic:
    issues: list[str] = []
    if not runtime.python.is_file():
        issues.append(f"missing Python executable: {runtime.python}")
    if not (runtime.repository / "lite_avatar.py").is_file():
        issues.append(f"missing LiteAvatar CLI: {runtime.repository / 'lite_avatar.py'}")
    if runtime.repository.exists():
        issues.extend(_inspect_repository(runtime.repository))
    for relative, expected_size in LITEAVATAR_WEIGHT_FILES.items():
        weight = runtime.repository / relative
        if not weight.is_file():
            issues.append(f"missing weight: {relative}")
        elif weight.stat().st_size != expected_size:
            issues.append(f"invalid weight size: {relative}")
        elif _sha256(weight) != LITEAVATAR_WEIGHT_HASHES[relative]:
            issues.append(f"invalid weight hash: {relative}")
    avatar_dir = runtime.repository / "data/sample_data/preload"
    for name, expected_hash in LITEAVATAR_SAMPLE_HASHES.items():
        asset = avatar_dir / name
        if not asset.is_file():
            issues.append(f"missing sample avatar asset: {name}")
        elif _sha256(asset) != expected_hash:
            issues.append(f"invalid sample avatar asset: {name}")
    reference_root = avatar_dir / "ref_frames"
    reference_frames = sorted(reference_root.glob("*.jpg"))
    expected_names = [f"ref_{index:05d}.jpg" for index in range(150)]
    if [path.name for path in reference_frames] != expected_names:
        issues.append("invalid sample avatar reference frame set")
    else:
        digest = hashlib.sha256()
        for frame in reference_frames:
            digest.update(frame.name.encode())
            digest.update(b"\0")
            digest.update(frame.read_bytes())
        if digest.hexdigest() != LITEAVATAR_REFERENCE_FRAMES_SHA256:
            issues.append("invalid sample avatar reference frame hash")

    device = "unknown"
    if runtime.python.is_file():
        try:
            probe = subprocess.run(
                [
                    str(runtime.python),
                    "-c",
                    (
                        "import json,sys,torch,onnxruntime; "
                        "print(json.dumps({'python':list(sys.version_info[:3]),'device':'cpu',"
                        "'providers':onnxruntime.get_available_providers()}))"
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
            if probe.returncode:
                issues.append("LiteAvatar Python dependency probe failed")
            else:
                payload = json.loads(probe.stdout)
                device = str(payload["device"])
                if tuple(payload["python"]) != REQUIRED_PYTHON:
                    issues.append(f"unexpected Python version: {tuple(payload['python'])}")
                if "CPUExecutionProvider" not in payload["providers"]:
                    issues.append("ONNX Runtime CPU provider is unavailable")
        except (OSError, subprocess.TimeoutExpired):
            issues.append("LiteAvatar Python dependency probe failed")
        except (json.JSONDecodeError, KeyError, TypeError):
            issues.append("LiteAvatar Python dependency probe returned invalid JSON")
    return LiteAvatarDiagnostic(
        not issues, device, sum(LITEAVATAR_WEIGHT_FILES.values()), tuple(issues)
    )


def _verify_wav(ffprobe: Path, audio: Path) -> None:
    probe = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            str(audio),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams or streams[0].get("sample_rate") != "16000" or streams[0].get("channels") != 1:
        raise ValueError("LiteAvatar requires a 16 kHz mono WAV input")


def _publish_file_no_replace(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError:
        raise FileExistsError(destination) from None
    source.unlink()


def run_liteavatar_render(
    runtime: LiteAvatarRuntime,
    spec: LiteAvatarRenderSpec,
    *,
    ffmpeg: Path,
    ffprobe: Path,
    timeout_seconds: float = 900,
) -> LiteAvatarRenderResult:
    if not spec.audio.is_file():
        raise FileNotFoundError(spec.audio)
    if not spec.avatar_dir.is_dir():
        raise FileNotFoundError(spec.avatar_dir)
    build_liteavatar_render_command(runtime, spec, result_dir=Path("unused"))
    _verify_wav(ffprobe, spec.audio)
    diagnostic = inspect_liteavatar_runtime(runtime)
    if not diagnostic.ready:
        raise RuntimeError("LiteAvatar runtime is not ready: " + "; ".join(diagnostic.issues))
    output = spec.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix=".openrealtime-liteavatar-", dir=output.parent
    ) as temporary_value:
        temporary = Path(temporary_value)
        subprocess.run(
            build_liteavatar_render_command(runtime, spec, result_dir=temporary),
            cwd=runtime.repository,
            env={**os.environ, "LITEAVATAR_FFMPEG": str(ffmpeg)},
            check=True,
            timeout=timeout_seconds,
        )
        raw = temporary / "test_demo.mp4"
        partial = temporary / "normalized.mp4"
        subprocess.run(
            [
                str(ffmpeg),
                "-y",
                "-i",
                str(raw),
                "-vf",
                "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=25",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "24000",
                str(partial),
            ],
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        _publish_file_no_replace(partial, output)
    return LiteAvatarRenderResult(output, time.perf_counter() - started)


def _runtime_from_root(root: Path) -> LiteAvatarRuntime:
    resolved = root.resolve()
    return LiteAvatarRuntime(resolved / "repository", resolved / ".venv/bin/python")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--runtime-root", type=Path, default=Path("models/liteavatar"))
    render = subparsers.add_parser("render")
    render.add_argument("audio", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--runtime-root", type=Path, default=Path("models/liteavatar"))
    render.add_argument("--rights-confirmed", action="store_true")
    render.add_argument(
        "--usage-scope", choices=tuple(sorted(ALLOWED_USAGE_SCOPES)), default="internal_evaluation"
    )
    render.add_argument("--timeout-seconds", type=float, default=900)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    runtime = _runtime_from_root(args.runtime_root)
    if args.command == "diagnose":
        diagnostic = inspect_liteavatar_runtime(runtime)
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    ffmpeg = Path(shutil.which("ffmpeg") or "/missing/ffmpeg")
    ffprobe = Path(shutil.which("ffprobe") or "/missing/ffprobe")
    avatar_dir = runtime.repository / "data/sample_data/preload"
    result = run_liteavatar_render(
        runtime,
        LiteAvatarRenderSpec(
            args.audio, avatar_dir, args.output, args.rights_confirmed, args.usage_scope
        ),
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({"output": str(result.output_path), "render_seconds": result.render_seconds}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
