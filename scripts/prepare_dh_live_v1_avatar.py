"""Prepare a DH_live_mini v1 browser avatar from a silent 720x1280 base video."""

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
import tempfile
from pathlib import Path

from scripts.dh_live_v1_provider import (
    AVATAR_FILES,
    AVATAR_MANIFEST_NAME,
    AVATAR_MANIFEST_SCHEMA,
    DH_LIVE_V1_COMMIT,
    RENDERER_FILES,
    inspect_dh_live_v1_bundle,
)

PATCHED_SOURCE_TREE_SHA256 = "a06e75fbaf8dd73c2a02589080914f4e51af5877f20564c285d7d698b6dd3969"
DINET_WEIGHT_SIZE = 19_670_609
DINET_WEIGHT_SHA256 = "6d79c978e4ee19b2915c79a7b583038b67edd474d6d3f08d0d9d0394ded7b1e9"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_tree_sha256(repository: Path) -> str:
    digest = hashlib.sha256()
    candidates = sorted(repository.rglob("*"))
    if any(path.is_symlink() for path in candidates):
        raise ValueError("DH_live v1 source tree cannot contain symbolic links")
    if any(
        "__pycache__" in path.relative_to(repository).parts or path.suffix in {".pyc", ".pyo"}
        for path in candidates
    ):
        raise ValueError("DH_live v1 source tree cannot contain executable bytecode caches")
    for path in (candidate for candidate in candidates if candidate.is_file()):
        relative_path = path.relative_to(repository)
        if path.is_relative_to(repository / "checkpoint"):
            continue
        size = path.stat().st_size
        if size > 16 * 1024 * 1024:
            raise ValueError("DH_live v1 source file exceeds the integrity-check boundary")
        relative = relative_path.as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def inspect_dh_live_v1_runtime(runtime_root: Path) -> list[str]:
    issues: list[str] = []
    repository = runtime_root / "repository"
    python = runtime_root / ".venv/bin/python"
    weight = repository / "checkpoint/DINet_mini/epoch_40.pth"
    if not repository.is_dir() or repository.is_symlink():
        return ["missing or unsafe DH_live v1 repository"]
    try:
        if _source_tree_sha256(repository) != PATCHED_SOURCE_TREE_SHA256:
            issues.append("DH_live v1 patched source tree hash mismatch")
    except (OSError, ValueError):
        issues.append("DH_live v1 patched source tree is unsafe")
    if (
        not weight.is_file()
        or weight.is_symlink()
        or weight.stat().st_size != DINET_WEIGHT_SIZE
        or _sha256(weight) != DINET_WEIGHT_SHA256
    ):
        issues.append("missing or invalid DH_live v1 DINet checkpoint")
    if not python.is_file():
        issues.append("missing DH_live v1 Python runtime")
    elif not issues:
        try:
            probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "import cv2, mediapipe, torch; "
                        "assert hasattr(mediapipe, 'solutions'); "
                        "print('.'.join(map(str, __import__('sys').version_info[:3])))"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if probe.stdout.strip() != "3.10.20":
                issues.append("DH_live v1 Python must be 3.10.20")
        except (OSError, subprocess.SubprocessError):
            issues.append("DH_live v1 Python dependency probe failed")
    return issues


def _validate_input_video(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("input must be a bounded regular video file")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,nb_read_frames",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stream = json.loads(result.stdout)["streams"][0]
        numerator, denominator = (float(value) for value in stream["r_frame_rate"].split("/"))
        if denominator == 0:
            raise ValueError
        fps = numerator / denominator
        frames = int(stream["nb_read_frames"])
        if (
            int(stream["width"]) != 720
            or int(stream["height"]) != 1280
            or not math.isclose(fps, 25, abs_tol=0.01)
            or not 25 <= frames <= 1_500
        ):
            raise ValueError
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError("input must be 720x1280 at 25fps with 1-60 seconds of frames") from error


def _snapshot_input_video(source: Path, destination: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise ValueError("input must be a readable regular video file") from error
    try:
        metadata = os.fstat(descriptor)
        maximum_size = 256 * 1024 * 1024
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum_size:
            raise ValueError("input must be a bounded regular video file")
        with (
            os.fdopen(descriptor, "rb", closefd=False) as input_file,
            destination.open("xb") as output_file,
        ):
            copied = 0
            while chunk := input_file.read(min(1024 * 1024, maximum_size - copied + 1)):
                copied += len(chunk)
                if copied > maximum_size:
                    raise ValueError("input must be a bounded regular video file")
                output_file.write(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
        if copied != metadata.st_size:
            raise ValueError("input video changed while it was being snapshotted")
    finally:
        os.close(descriptor)


def _run(command: list[str], *, cwd: Path, timeout: int = 300) -> None:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        subprocess.run(command, cwd=cwd, check=True, env=environment, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"DH_live v1 preparation timed out after {timeout}s") from error


def prepare_dh_live_v1_avatar(
    *,
    runtime_root: Path,
    input_video: Path,
    output_bundle: Path,
    avatar_id: str,
    rights_confirmed: bool,
) -> dict[str, object]:
    if rights_confirmed is not True:
        raise ValueError("Avatar image and video evaluation rights must be confirmed")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", avatar_id):
        raise ValueError("avatar_id must use lowercase letters, numbers, and hyphens")
    runtime_root = runtime_root.resolve()
    input_video = input_video.absolute()
    output_bundle = output_bundle.resolve()
    if output_bundle.exists():
        raise FileExistsError(output_bundle)
    issues = inspect_dh_live_v1_runtime(runtime_root)
    if issues:
        raise RuntimeError("DH_live v1 runtime is not ready: " + "; ".join(issues))
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    repository = runtime_root / "repository"
    python = runtime_root / ".venv/bin/python"

    with tempfile.TemporaryDirectory(
        prefix=f".{output_bundle.name}.", dir=output_bundle.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        work = temporary / "work"
        bundle = temporary / "bundle"
        input_snapshot = temporary / "input.mp4"
        work.mkdir()
        bundle.mkdir()
        _snapshot_input_video(input_video, input_snapshot)
        _validate_input_video(input_snapshot)
        _run(
            [str(python), "data_preparation_mini.py", str(input_snapshot), str(work)],
            cwd=repository,
        )
        _run([str(python), "data_preparation_web.py", str(work)], cwd=repository)
        for relative in RENDERER_FILES:
            source = repository / "web_demo/static" / relative
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for relative in AVATAR_FILES:
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(work / relative, destination)
        files = {
            relative.as_posix(): {
                "size_bytes": (bundle / relative).stat().st_size,
                "sha256": _sha256(bundle / relative),
            }
            for relative in AVATAR_FILES
        }
        manifest = {
            "schema_version": AVATAR_MANIFEST_SCHEMA,
            "runtime_commit": DH_LIVE_V1_COMMIT,
            "avatar_id": avatar_id,
            "authorized": False,
            "usage_scope": "internal_evaluation",
            "source_video": {
                "size_bytes": input_snapshot.stat().st_size,
                "sha256": _sha256(input_snapshot),
            },
            "files": files,
        }
        manifest_path = bundle / AVATAR_MANIFEST_NAME
        with manifest_path.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        diagnostic = inspect_dh_live_v1_bundle(bundle)
        if not diagnostic.ready:
            raise RuntimeError(
                "generated DH_live v1 bundle is invalid: " + "; ".join(diagnostic.issues)
            )
        os.replace(bundle, output_bundle)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_video", type=Path)
    parser.add_argument("output_bundle", type=Path)
    parser.add_argument("--runtime-root", type=Path, default=Path("models/dh_live_v1"))
    parser.add_argument("--avatar-id", default="shuchang")
    parser.add_argument("--rights-confirmed", action="store_true")
    args = parser.parse_args()
    payload = prepare_dh_live_v1_avatar(
        runtime_root=args.runtime_root,
        input_video=args.input_video,
        output_bundle=args.output_bundle,
        avatar_id=args.avatar_id,
        rights_confirmed=args.rights_confirmed,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
