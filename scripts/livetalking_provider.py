"""Verified launcher for the local LiveTalking WebRTC service."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

LIVETALKING_REPOSITORY_URL = "https://github.com/lipku/LiveTalking.git"
LIVETALKING_COMMIT = "36837f90f8db3f59e1d7fcdd111a7db3842515d0"
LIVETALKING_PATCH_DIFF_SHA256 = "1d3251dfab5c280fcc1c0b17a014321ea81c56fed7e11b4cfa698ed6467cb000"
WAV2LIP_COMPOSITOR_SHA256 = "26b6487c5f032cb05a583d0bb7159e7b2c543bc86543402ff669e7380b13504b"
WAV2LIP_INFERENCE_STRIDE_SHA256 = "ff3ed5080c36edb3e0089a506c7373448795dd1a4eed4f5456674c06a94180c8"
WAV2LIP_CHECKPOINTS = {
    96: ("wav2lip.pth", "b78b681b68ad9fe6c6fb1debc6ff43ad05834a8af8a62ffc4167b7b34ef63c37"),
    256: ("wav2lip256.pth", "b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173"),
}
REQUIRED_PYTHON = (3, 10, 20)
PROBE_TIMEOUT_SECONDS = 60
DEFAULT_ALLOWED_ORIGINS = "http://127.0.0.1:3010,http://localhost:3010"
NONCOMMERCIAL_USAGE_SCOPES = {"internal_evaluation", "research", "personal"}
AVATAR_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LiveTalkingRuntime:
    repository: Path
    python: Path


@dataclass(frozen=True)
class LiveTalkingDiagnostic:
    ready: bool
    device: str
    avatar_id: str | None
    frame_count: int | None
    issues: tuple[str, ...]


def _validate_avatar_id(avatar_id: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", avatar_id) is None:
        raise ValueError("avatar_id must be a canonical ASCII identifier")


def build_livetalking_server_command(
    runtime: LiveTalkingRuntime,
    *,
    avatar_id: str,
    port: int,
    batch_size: int = 4,
    inference_stride: int = 2,
    model_size: int = 256,
    usage_scope: str = "internal_evaluation",
) -> list[str]:
    _validate_avatar_id(avatar_id)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not 1 <= batch_size <= 16:
        raise ValueError("batch_size must be between 1 and 16")
    if inference_stride not in (1, 2):
        raise ValueError("inference_stride must be 1 or 2")
    if batch_size % inference_stride != 0:
        raise ValueError("batch_size must be divisible by inference_stride")
    if model_size not in WAV2LIP_CHECKPOINTS:
        raise ValueError("model_size must be 96 or 256")
    if usage_scope not in NONCOMMERCIAL_USAGE_SCOPES:
        raise ValueError("Standard Wav2Lip is restricted to non-commercial usage scopes")
    return [
        str(runtime.python),
        str(runtime.repository / "app.py"),
        "--config",
        "",
        "--transport",
        "webrtc",
        "--model",
        "wav2lip",
        "--avatar_id",
        avatar_id,
        "--batch_size",
        str(batch_size),
        "--modelres",
        str(model_size),
        "--modelfile",
        str(runtime.repository / "models" / WAV2LIP_CHECKPOINTS[model_size][0]),
        "--wav2lip_inference_stride",
        str(inference_stride),
        "--listenport",
        str(port),
        "--stun",
        "",
    ]


def build_livetalking_server_environment(
    base: dict[str, str] | None = None,
    *,
    model_size: int = 256,
) -> dict[str, str]:
    """Return the locked-down environment used by the supported local launcher."""

    if model_size not in WAV2LIP_CHECKPOINTS:
        raise ValueError("model_size must be 96 or 256")
    environment = dict(os.environ if base is None else base)
    environment.update(
        {
            "LIVETALKING_BIND_HOST": "127.0.0.1",
            "LIVETALKING_ALLOWED_ORIGINS": DEFAULT_ALLOWED_ORIGINS,
            "LIVETALKING_ENABLE_MANAGEMENT_ROUTES": "0",
            "LIVETALKING_ENABLE_AVATAR_PREPARATION_ROUTES": "1",
            "LIVETALKING_WAV2LIP_MODEL_SIZE": str(model_size),
            "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        }
    )
    return environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_png_dimensions(python: Path, paths: list[Path]) -> list[tuple[int, int]]:
    """Decode every frame with OpenCV in the isolated LiveTalking runtime."""

    decoder = """
import cv2
import json
import sys

dimensions = []
for value in json.loads(sys.stdin.read()):
    image = cv2.imread(value, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"unable to decode PNG: {value}")
    dimensions.append([int(image.shape[1]), int(image.shape[0])])
print(json.dumps(dimensions))
"""
    result = subprocess.run(
        [str(python), "-c", decoder],
        input=json.dumps([str(path) for path in paths]),
        capture_output=True,
        check=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    decoded = json.loads(result.stdout)
    if (
        type(decoded) is not list
        or len(decoded) != len(paths)
        or any(
            type(item) is not list
            or len(item) != 2
            or any(type(value) is not int or value <= 0 for value in item)
            for item in decoded
        )
    ):
        raise ValueError("invalid image decoder response")
    return [(item[0], item[1]) for item in decoded]


def _inspect_avatar(
    repository: Path,
    avatar_id: str,
    *,
    python: Path,
    face_size: int = 256,
) -> tuple[int | None, list[str]]:
    try:
        _validate_avatar_id(avatar_id)
    except ValueError as error:
        return None, [str(error)]
    avatars_root = (repository / "data/avatars").resolve()
    avatar_root = (avatars_root / avatar_id).resolve()
    if not avatar_root.is_relative_to(avatars_root):
        return None, [f"avatar path escapes the avatar root: {avatar_id}"]
    manifest_path = avatar_root / "manifest.json"
    coords_path = avatar_root / "coords.json"
    if not manifest_path.is_file() or not coords_path.is_file():
        return None, [f"missing preprocessed avatar: {avatar_id}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        coords = json.loads(coords_path.read_text(encoding="utf-8"))
        if type(manifest) is not dict or type(coords) is not list:
            raise ValueError
        if manifest.get("schema_version") != AVATAR_MANIFEST_SCHEMA_VERSION:
            raise ValueError
        if manifest.get("avatar_id") != avatar_id or manifest.get("rights_confirmed") is not True:
            raise ValueError
        frame_count = manifest.get("frame_count")
        if type(frame_count) is not int or frame_count <= 0:
            raise ValueError
        if manifest.get("fps") != 25 or manifest.get("face_size") != face_size:
            raise ValueError
        per_frame_boxes = manifest.get("face_box_mode") == "per_frame"
        face_box = manifest.get("face_box")
        if not per_frame_boxes and (
            type(face_box) is not list
            or len(face_box) != 4
            or any(type(value) is not int for value in face_box)
        ):
            raise ValueError
        source = Path(manifest.get("source", ""))
        source_hash = manifest.get("source_sha256")
        if not source.is_file() or not re.fullmatch(r"[0-9a-f]{64}", str(source_hash)):
            raise ValueError
        if _sha256(source) != source_hash:
            raise ValueError
        expected_names = [f"{index:08d}.png" for index in range(frame_count)]
        full_frames = sorted((avatar_root / "full_imgs").glob("*.png"))
        face_frames = sorted((avatar_root / "face_imgs").glob("*.png"))
        if [path.name for path in full_frames] != expected_names:
            raise ValueError
        if [path.name for path in face_frames] != expected_names or len(coords) != frame_count:
            raise ValueError
        dimensions = _decode_png_dimensions(python, full_frames + face_frames)
        full_dimensions = dimensions[:frame_count]
        face_dimensions = dimensions[frame_count:]
        for index, coordinate in enumerate(coords):
            width, height = full_dimensions[index]
            if face_dimensions[index] != (face_size, face_size):
                raise ValueError
            if (
                type(coordinate) is not list
                or len(coordinate) != 4
                or any(type(value) is not int or not math.isfinite(value) for value in coordinate)
            ):
                raise ValueError
            y1, y2, x1, x2 = coordinate
            if not per_frame_boxes and [y1, y2, x1, x2] != face_box:
                raise ValueError
            if min(coordinate) < 0 or y2 <= y1 or x2 <= x1 or y2 > height or x2 > width:
                raise ValueError
        return frame_count, []
    except (
        OSError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
    ):
        return None, [f"invalid preprocessed avatar manifest: {avatar_id}"]


def _inspect_repository(repository: Path) -> list[str]:
    git = shutil.which("git")
    if not git:
        return ["missing Git executable"]
    if not (repository / ".git").is_dir():
        return [f"LiveTalking source is not a Git checkout: {repository}"]
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
        staged = subprocess.run(
            [git, "-C", str(repository), "diff", "--cached", "--quiet"],
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).returncode
        status_lines = subprocess.run(
            [git, "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ["LiveTalking Git verification failed"]
    issues: list[str] = []
    if origin != LIVETALKING_REPOSITORY_URL:
        issues.append(f"unexpected repository origin: {origin}")
    if commit != LIVETALKING_COMMIT:
        issues.append(f"unexpected repository commit: {commit}")
    if staged:
        issues.append("repository has staged changes")
    if hashlib.sha256(diff).hexdigest() != LIVETALKING_PATCH_DIFF_SHA256:
        issues.append("LiveTalking compatibility patch hash mismatch")
    compositor_relative_path = "avatars/wav2lip/compositing.py"
    compositor = repository / compositor_relative_path
    if not compositor.is_file() or _sha256(compositor) != WAV2LIP_COMPOSITOR_SHA256:
        issues.append("missing or invalid Wav2Lip compositor")
    stride_helper_relative_path = "avatars/wav2lip/inference_stride.py"
    stride_helper = repository / stride_helper_relative_path
    if (
        not stride_helper.is_file()
        or _sha256(stride_helper) != WAV2LIP_INFERENCE_STRIDE_SHA256
    ):
        issues.append("missing or invalid Wav2Lip inference stride helper")
    for line in status_lines:
        if line.startswith("?? "):
            relative_path = line[3:]
            if relative_path not in {compositor_relative_path, stride_helper_relative_path}:
                issues.append(f"repository has unexpected untracked file: {relative_path}")
    return issues


def inspect_livetalking_runtime(
    runtime: LiveTalkingRuntime,
    *,
    avatar_id: str | None = None,
    model_size: int = 256,
) -> LiveTalkingDiagnostic:
    issues: list[str] = []
    if model_size not in WAV2LIP_CHECKPOINTS:
        raise ValueError("model_size must be 96 or 256")
    if not runtime.python.is_file():
        issues.append(f"missing Python executable: {runtime.python}")
    if not (runtime.repository / "app.py").is_file():
        issues.append(f"missing LiveTalking app: {runtime.repository / 'app.py'}")
    if runtime.repository.exists():
        issues.extend(_inspect_repository(runtime.repository))

    checkpoint_name, checkpoint_hash = WAV2LIP_CHECKPOINTS[model_size]
    checkpoint = runtime.repository / "models" / checkpoint_name
    if not checkpoint.is_file():
        issues.append(f"missing verified Wav2Lip checkpoint: {checkpoint}")
    elif _sha256(checkpoint) != checkpoint_hash:
        issues.append("invalid LiveTalking Wav2Lip checkpoint hash")

    frame_count: int | None = None
    if avatar_id:
        frame_count, avatar_issues = _inspect_avatar(
            runtime.repository,
            avatar_id,
            python=runtime.python,
            face_size=model_size,
        )
        issues.extend(avatar_issues)

    device = "unknown"
    if runtime.python.is_file():
        try:
            probe = subprocess.run(
                [
                    str(runtime.python),
                    "-c",
                    (
                        "import json, sys, torch; "
                        "device=('mps' if torch.backends.mps.is_available() else "
                        "'cuda' if torch.cuda.is_available() else 'cpu'); "
                        "print(json.dumps({'device': device, 'python': list(sys.version_info[:3])}))"
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            issues.append("LiveTalking Python probe timed out")
        else:
            if probe.returncode != 0:
                issues.append("LiveTalking Python cannot import torch")
            else:
                try:
                    payload = json.loads(probe.stdout)
                    device = str(payload["device"])
                    if tuple(payload["python"]) != REQUIRED_PYTHON:
                        issues.append(f"unexpected Python version: {tuple(payload['python'])}")
                except (json.JSONDecodeError, KeyError, TypeError):
                    issues.append("LiveTalking Python probe returned invalid JSON")

    if not issues:
        try:
            probe = subprocess.run(
                [str(runtime.python), str(runtime.repository / "app.py"), "--help"],
                capture_output=True,
                check=False,
                cwd=runtime.repository,
                env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            issues.append("LiveTalking import probe timed out")
        else:
            if probe.returncode != 0:
                issues.append("LiveTalking import probe failed")

    return LiveTalkingDiagnostic(
        ready=not issues,
        device=device,
        avatar_id=avatar_id,
        frame_count=frame_count,
        issues=tuple(issues),
    )


def _runtime_from_root(root: Path) -> LiveTalkingRuntime:
    root = root.resolve()
    return LiveTalkingRuntime(root / "repository", root / ".venv/bin/python")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--runtime-root", type=Path, default=Path("models/livetalking"))
    diagnose.add_argument("--avatar-id")
    diagnose.add_argument("--model-size", type=int, choices=(96, 256), default=256)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--runtime-root", type=Path, default=Path("models/livetalking"))
    serve.add_argument("--avatar-id", required=True)
    serve.add_argument("--port", type=int, default=8010)
    serve.add_argument("--batch-size", type=int, default=4)
    serve.add_argument("--inference-stride", type=int, choices=(1, 2), default=2)
    serve.add_argument("--model-size", type=int, choices=(96, 256), default=256)
    serve.add_argument(
        "--usage-scope",
        choices=tuple(sorted(NONCOMMERCIAL_USAGE_SCOPES)),
        default="internal_evaluation",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    runtime = _runtime_from_root(args.runtime_root)
    if args.command == "diagnose":
        diagnostic = inspect_livetalking_runtime(
            runtime, avatar_id=args.avatar_id, model_size=args.model_size
        )
        print(json.dumps(asdict(diagnostic), ensure_ascii=False, sort_keys=True))
        return 0 if diagnostic.ready else 2
    diagnostic = inspect_livetalking_runtime(
        runtime, avatar_id=args.avatar_id, model_size=args.model_size
    )
    if not diagnostic.ready:
        raise RuntimeError("LiveTalking runtime is not ready: " + "; ".join(diagnostic.issues))
    command = build_livetalking_server_command(
        runtime,
        avatar_id=args.avatar_id,
        port=args.port,
        batch_size=args.batch_size,
        inference_stride=args.inference_stride,
        model_size=args.model_size,
        usage_scope=args.usage_scope,
    )
    environment = build_livetalking_server_environment(model_size=args.model_size)
    project_root = runtime.repository.parents[2]
    environment["LIVETALKING_AVATAR_SOURCE_ROOTS"] = os.pathsep.join((
        str(project_root / "public"),
        str(project_root / "data"),
        str(runtime.repository / "data"),
    ))
    os.chdir(runtime.repository)
    os.execve(command[0], command, environment)
    raise AssertionError("os.execve returned unexpectedly")


if __name__ == "__main__":
    raise SystemExit(main())
