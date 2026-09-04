"""Prepare a fixed-box, JSON-coordinate LiveTalking avatar from a motion video."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AvatarPreparationPlan:
    source: Path
    avatar_root: Path
    face_box: tuple[int, int, int, int]
    face_size: int
    frames_per_second: int
    rights_confirmed: bool

    def __post_init__(self) -> None:
        _validate_plan(self)


def _validate_avatar_id(value: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is None:
        raise ValueError("avatar_root must end in a canonical ASCII avatar ID")


def _validate_plan(plan: AvatarPreparationPlan) -> None:
    if plan.rights_confirmed is not True:
        raise ValueError("Video, portrait, and identity rights must be confirmed")
    if not plan.source.is_file():
        raise FileNotFoundError(plan.source)
    if plan.source.resolve() == plan.avatar_root.resolve():
        raise ValueError("Avatar source and output must be different paths")
    _validate_avatar_id(plan.avatar_root.name)
    if len(plan.face_box) != 4 or any(type(value) is not int for value in plan.face_box):
        raise ValueError("face_box must contain four integer coordinates")
    y1, y2, x1, x2 = plan.face_box
    if min(plan.face_box) < 0 or y2 <= y1 or x2 <= x1:
        raise ValueError("face_box must contain non-negative y1 y2 x1 x2 coordinates")
    if plan.face_size not in (96, 256):
        raise ValueError("Wav2Lip avatars require face_size=96 or face_size=256")
    if plan.frames_per_second != 25:
        raise ValueError("LiveTalking evaluation avatars require 25 FPS")


def build_avatar_preparation_plan(
    source: Path,
    *,
    avatar_root: Path,
    face_box: tuple[int, int, int, int],
    rights_confirmed: bool,
    face_size: int = 256,
) -> AvatarPreparationPlan:
    return AvatarPreparationPlan(
        source=source.resolve(),
        avatar_root=avatar_root.resolve(),
        face_box=face_box,
        face_size=face_size,
        frames_per_second=25,
        rights_confirmed=rights_confirmed,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_livetalking_avatar(plan: AvatarPreparationPlan) -> int:
    _validate_plan(plan)
    import cv2

    if plan.avatar_root.exists():
        raise FileExistsError(f"Avatar output already exists: {plan.avatar_root}")
    plan.avatar_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{plan.avatar_root.name}.", dir=plan.avatar_root.parent)
    )
    full_images = temporary_root / "full_imgs"
    face_images = temporary_root / "face_imgs"
    full_images.mkdir()
    face_images.mkdir()
    capture = cv2.VideoCapture(str(plan.source))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or abs(fps - plan.frames_per_second) > 0.01:
            raise ValueError(f"Avatar source must be {plan.frames_per_second} FPS; found {fps}")
        coordinates: list[list[int]] = []
        index = 0
        y1, y2, x1, x2 = plan.face_box
        while True:
            read, frame = capture.read()
            if not read:
                break
            height, width = frame.shape[:2]
            if y2 > height or x2 > width:
                raise ValueError(
                    f"face_box {plan.face_box} exceeds frame dimensions {width}x{height}"
                )
            face = frame[y1:y2, x1:x2]
            face = cv2.resize(face, (plan.face_size, plan.face_size))
            frame_name = f"{index:08d}.png"
            if not cv2.imwrite(str(full_images / frame_name), frame):
                raise RuntimeError(f"Failed to write full frame {index}")
            if not cv2.imwrite(str(face_images / frame_name), face):
                raise RuntimeError(f"Failed to write face frame {index}")
            coordinates.append([y1, y2, x1, x2])
            index += 1
        if index == 0:
            raise ValueError("Avatar source contains no readable frames")
        (temporary_root / "coords.json").write_text(
            json.dumps(coordinates, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "avatar_id": plan.avatar_root.name,
            "source": str(plan.source),
            "source_sha256": _sha256(plan.source),
            "frame_count": index,
            "fps": plan.frames_per_second,
            "face_box": list(plan.face_box),
            "face_size": plan.face_size,
            "rights_confirmed": plan.rights_confirmed,
        }
        (temporary_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_root, plan.avatar_root)
        return index
    finally:
        capture.release()
        if temporary_root.exists():
            shutil.rmtree(temporary_root, ignore_errors=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("avatar_root", type=Path)
    parser.add_argument("--box", nargs=4, type=int, required=True, metavar=("Y1", "Y2", "X1", "X2"))
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--face-size", type=int, choices=(96, 256), default=256)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_avatar_preparation_plan(
        args.source,
        avatar_root=args.avatar_root,
        face_box=tuple(args.box),
        rights_confirmed=args.rights_confirmed,
        face_size=args.face_size,
    )
    frame_count = prepare_livetalking_avatar(plan)
    payload = asdict(plan)
    payload["source"] = str(plan.source)
    payload["avatar_root"] = str(plan.avatar_root)
    payload["frame_count"] = frame_count
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
