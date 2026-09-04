"""Verified local Wav2Lip offline lip-sync provider."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

WAV2LIP_REPOSITORY_URL = "https://github.com/Rudrabha/Wav2Lip.git"
WAV2LIP_COMMIT = "bac9a81e63ecc153202353372e5724b83d9e6322"
WAV2LIP_PATCH_DIFF_SHA256 = "3e80ae78ec8565cfb7fc4a5f809e837ad868637d6dbd2ddc9bc29ed4e740d4da"
REQUIRED_PYTHON = (3, 10, 20)
PROBE_TIMEOUT_SECONDS = 60
WAV2LIP_WEIGHT_FILES = {
    Path("checkpoints/wav2lip.pth"): 435_807_851,
    Path("face_detection/detection/sfd/s3fd.pth"): 89_843_225,
}
WAV2LIP_WEIGHT_HASHES = {
    Path("checkpoints/wav2lip.pth"): (
        "b78b681b68ad9fe6c6fb1debc6ff43ad05834a8af8a62ffc4167b7b34ef63c37"
    ),
    Path("face_detection/detection/sfd/s3fd.pth"): (
        "619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543"
    ),
}
NONCOMMERCIAL_USAGE_SCOPES = {"internal_evaluation", "research", "personal"}


@dataclass(frozen=True)
class Wav2LipRuntime:
    repository: Path
    python: Path


@dataclass(frozen=True)
class Wav2LipRenderSpec:
    face: Path
    audio: Path
    output: Path
    rights_confirmed: bool
    device: str = "auto"
    face_box: tuple[int, int, int, int] | None = None
    usage_scope: str = "internal_evaluation"


@dataclass(frozen=True)
class Wav2LipRuntimeDiagnostic:
    ready: bool
    device: str
    weights_bytes: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class Wav2LipRenderResult:
    output_path: Path
    render_seconds: float


def build_wav2lip_render_command(
    runtime: Wav2LipRuntime,
    spec: Wav2LipRenderSpec,
) -> list[str]:
    if not spec.rights_confirmed:
        raise ValueError("Face, motion-video, and voice rights must be confirmed")
    if spec.audio.suffix.lower() != ".wav":
        raise ValueError("Wav2Lip local rendering requires a pre-normalized WAV input")
    if spec.device not in {"auto", "mps", "cpu", "cuda"}:
        raise ValueError(f"Unsupported Wav2Lip device: {spec.device}")
    if spec.usage_scope not in NONCOMMERCIAL_USAGE_SCOPES:
        raise ValueError("Standard Wav2Lip is restricted to non-commercial usage scopes")
    command = [
        str(runtime.python),
        str(runtime.repository / "inference.py"),
        "--checkpoint_path",
        str(runtime.repository / "checkpoints/wav2lip.pth"),
        "--face",
        str(spec.face),
        "--audio",
        str(spec.audio),
        "--outfile",
        str(spec.output),
    ]
    if spec.face_box is not None:
        y1, y2, x1, x2 = spec.face_box
        if min(spec.face_box) < 0 or y2 <= y1 or x2 <= x1:
            raise ValueError("Wav2Lip face box must be non-negative y1 y2 x1 x2 coordinates")
        command.extend(["--box", *(str(value) for value in spec.face_box)])
    return command


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_repository(repository: Path) -> list[str]:
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
        staged = subprocess.run(
            [git, "-C", str(repository), "diff", "--cached", "--quiet"],
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).returncode
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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ["official repository Git verification failed"]

    issues: list[str] = []
    if origin != WAV2LIP_REPOSITORY_URL:
        issues.append(f"unexpected repository origin: {origin}")
    if commit != WAV2LIP_COMMIT:
        issues.append(f"unexpected repository commit: {commit}")
    if staged:
        issues.append("repository has staged changes")
    if hashlib.sha256(diff).hexdigest() != WAV2LIP_PATCH_DIFF_SHA256:
        issues.append("repository compatibility patch hash mismatch")

    allowed_weights = {path.as_posix() for path in WAV2LIP_WEIGHT_FILES}
    for line in status_lines:
        status, changed_path = line[:2], line[3:]
        if status != "??":
            continue
        if changed_path in allowed_weights:
            continue
        issues.append(f"repository has unexpected untracked file: {changed_path}")
    return issues


def inspect_wav2lip_runtime(
    runtime: Wav2LipRuntime,
    *,
    ffmpeg: Path,
) -> Wav2LipRuntimeDiagnostic:
    issues: list[str] = []
    inference = runtime.repository / "inference.py"
    if not runtime.python.is_file():
        issues.append(f"missing Python executable: {runtime.python}")
    if not inference.is_file():
        issues.append(f"missing official inference script: {inference}")
    if not ffmpeg.is_file():
        issues.append(f"missing FFmpeg executable: {ffmpeg}")
    if runtime.repository.exists():
        issues.extend(_inspect_repository(runtime.repository))

    for relative_path, expected_size in WAV2LIP_WEIGHT_FILES.items():
        weight = runtime.repository / relative_path
        if not weight.is_file():
            issues.append(f"missing weight: {relative_path.as_posix()}")
        elif weight.stat().st_size != expected_size:
            issues.append(f"invalid weight size: {relative_path.as_posix()}")
        elif _sha256(weight) != WAV2LIP_WEIGHT_HASHES[relative_path]:
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
            if probe.returncode != 0:
                issues.append("Python runtime cannot import torch")
            else:
                try:
                    payload = json.loads(probe.stdout)
                    device = str(payload["device"])
                    version = tuple(int(part) for part in payload["python"])
                    if version != tuple(REQUIRED_PYTHON):
                        issues.append(f"unexpected Python version: {version}")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    issues.append("Python device probe returned invalid JSON")

    if not issues:
        try:
            cli_probe = subprocess.run(
                [str(runtime.python), str(inference), "--help"],
                capture_output=True,
                check=False,
                cwd=runtime.repository,
                env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            issues.append("official Wav2Lip CLI import probe timed out")
        else:
            if cli_probe.returncode != 0:
                issues.append("official Wav2Lip CLI import probe failed")

    return Wav2LipRuntimeDiagnostic(
        ready=not issues,
        device=device,
        weights_bytes=sum(WAV2LIP_WEIGHT_FILES.values()),
        issues=tuple(issues),
    )


def _resolve_device(requested: str, observed: str) -> str:
    if requested == "auto":
        return observed if observed in {"mps", "cuda", "cpu"} else "cpu"
    return requested


def _verify_video(ffprobe: Path, output: Path) -> None:
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Wav2Lip output is missing or empty: {output}")
    result = subprocess.run(
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
            str(output),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError(f"Wav2Lip output has no video stream: {output}")
    duration = float(streams[0].get("duration") or 0)
    frames = int(streams[0].get("nb_frames") or 0)
    if duration <= 0 and frames <= 0:
        raise RuntimeError(f"Wav2Lip output has no frames or duration: {output}")


def _publish_file_no_replace(source: Path, destination: Path) -> None:
    """Publish a same-filesystem result without replacing an existing output."""

    try:
        os.link(source, destination)
    except FileExistsError:
        raise FileExistsError(destination) from None
    source.unlink()


def run_wav2lip_render(
    runtime: Wav2LipRuntime,
    spec: Wav2LipRenderSpec,
    *,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
    timeout_seconds: float = 900,
) -> Wav2LipRenderResult:
    if not spec.face.is_file():
        raise FileNotFoundError(spec.face)
    if not spec.audio.is_file():
        raise FileNotFoundError(spec.audio)
    ffmpeg = ffmpeg or Path(shutil.which("ffmpeg") or "/missing/ffmpeg")
    ffprobe = ffprobe or Path(shutil.which("ffprobe") or "/missing/ffprobe")
    diagnostic = inspect_wav2lip_runtime(runtime, ffmpeg=ffmpeg)
    if not diagnostic.ready:
        raise RuntimeError("Wav2Lip runtime is not ready: " + "; ".join(diagnostic.issues))

    output = spec.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.partial{output.suffix}")
    resolved_spec = Wav2LipRenderSpec(
        face=spec.face.resolve(),
        audio=spec.audio.resolve(),
        output=partial,
        rights_confirmed=spec.rights_confirmed,
        device=_resolve_device(spec.device, diagnostic.device),
        face_box=spec.face_box,
        usage_scope=spec.usage_scope,
    )
    env = {
        **os.environ,
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "WAV2LIP_DEVICE_OVERRIDE": resolved_spec.device,
    }
    started = time.perf_counter()
    lock_path = runtime.repository.parent / ".wav2lip-render.lock"
    try:
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                if output.exists():
                    raise FileExistsError(output)
                subprocess.run(
                    build_wav2lip_render_command(runtime, resolved_spec),
                    cwd=runtime.repository,
                    env=env,
                    check=True,
                    timeout=timeout_seconds,
                )
                render_seconds = time.perf_counter() - started
                _verify_video(ffprobe, partial)
                _publish_file_no_replace(partial, output)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        partial.unlink(missing_ok=True)
    return Wav2LipRenderResult(output_path=output, render_seconds=render_seconds)


def _runtime_from_root(runtime_root: Path) -> Wav2LipRuntime:
    root = runtime_root.resolve()
    return Wav2LipRuntime(root / "repository", root / ".venv/bin/python")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--runtime-root", type=Path, default=Path("models/wav2lip"))
    render = subparsers.add_parser("render")
    render.add_argument("face", type=Path)
    render.add_argument("audio", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--runtime-root", type=Path, default=Path("models/wav2lip"))
    render.add_argument("--device", choices=("auto", "mps", "cpu", "cuda"), default="auto")
    render.add_argument("--box", nargs=4, type=int, metavar=("Y1", "Y2", "X1", "X2"))
    render.add_argument("--rights-confirmed", action="store_true")
    render.add_argument(
        "--usage-scope",
        choices=tuple(sorted(NONCOMMERCIAL_USAGE_SCOPES)),
        default="internal_evaluation",
    )
    render.add_argument("--timeout-seconds", type=float, default=900)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    runtime = _runtime_from_root(args.runtime_root)
    ffmpeg = Path(shutil.which("ffmpeg") or "/missing/ffmpeg")
    if args.command == "diagnose":
        diagnostic = inspect_wav2lip_runtime(runtime, ffmpeg=ffmpeg)
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    result = run_wav2lip_render(
        runtime,
        Wav2LipRenderSpec(
            face=args.face,
            audio=args.audio,
            output=args.output,
            rights_confirmed=args.rights_confirmed,
            device=args.device,
            face_box=tuple(args.box) if args.box else None,
            usage_scope=args.usage_scope,
        ),
        ffmpeg=ffmpeg,
        ffprobe=Path(shutil.which("ffprobe") or "/missing/ffprobe"),
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {"output": str(result.output_path), "render_seconds": result.render_seconds},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
