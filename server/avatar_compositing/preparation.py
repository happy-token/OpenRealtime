"""Prepare new motion assets in OpenRealtime's own store, leaving references read-only."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def asset_path(roots: tuple[Path, ...], avatar_id: str) -> Path:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", avatar_id) is None:
        raise ValueError("Invalid avatar ID")
    for root in roots:
        path = (root / avatar_id).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Avatar path escapes asset root")
        if path.is_dir():
            return path
    raise FileNotFoundError(avatar_id)


def is_prepared(path: Path, model_size: int) -> bool:
    try:
        manifest = json.loads((path / "manifest.json").read_text())
        return (manifest.get("fps") == 25 and manifest.get("face_size") == model_size
                and manifest.get("avatar_id") == path.name and manifest.get("rights_confirmed") is True
                and (path / "coords.json").is_file()
                and (path / "full_imgs/00000000.png").is_file()
                and (path / "face_imgs/00000000.png").is_file())
    except (OSError, ValueError):
        return False


def prepare(source: Path, root: Path, avatar_id: str, size: int, progress) -> None:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", avatar_id) is None or size not in (96, 256):
        raise ValueError("Invalid avatar preparation parameters")
    root.mkdir(parents=True, exist_ok=True)
    destination = root / avatar_id
    if destination.exists():
        raise FileExistsError("Avatar already exists")
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=root) as directory:
        stage = Path(directory)
        full, faces = stage / "full_imgs", stage / "face_imgs"
        full.mkdir()
        faces.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(source), "-t", "60",
                        "-vf", "fps=25,scale=w='min(768,iw)':h='min(768,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-start_number", "0", str(full / "%08d.png")],
                       check=True, timeout=120, capture_output=True)
        paths = sorted(full.glob("*.png"))
        if not paths:
            raise ValueError("Motion video contains no decodable frames")
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        boxes = []
        previous = None
        for index, path in enumerate(paths):
            image = cv2.imread(str(path))
            height, width = image.shape[:2]
            candidates = detector.detectMultiScale(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                                                   scaleFactor=1.08, minNeighbors=4,
                                                   minSize=(max(36, min(height, width) // 10),) * 2)
            if len(candidates):
                if previous is None:
                    x, y, w, h = max(candidates, key=lambda item: item[2] * item[3])
                else:
                    previous_box = previous
                    x, y, w, h = min(candidates, key=lambda item:
                                    (item[0] + item[2] / 2 - (previous_box[2] + previous_box[3]) / 2) ** 2
                                    + (item[1] + item[3] / 2 - (previous_box[0] + previous_box[1]) / 2) ** 2)
                previous = (max(0, int(y)), min(height, int(y + h + 10)),
                            max(0, int(x)), min(width, int(x + w)))
            if previous is None:
                raise ValueError("No face found in the motion base")
            boxes.append(previous)
            progress(10 + int(60 * (index + 1) / len(paths)))
        box_array = np.asarray(boxes)
        smoothed = [np.rint(box_array[max(0, i - 2):min(len(boxes), i + 3)].mean(axis=0)).astype(int)
                    for i in range(len(boxes))]
        coords = []
        for index, (path, box) in enumerate(zip(paths, smoothed)):
            y1, y2, x1, x2 = (int(value) for value in box)
            frame = cv2.imread(str(path))
            crop = cv2.resize(frame[y1:y2, x1:x2], (size, size))
            if not cv2.imwrite(str(faces / path.name), crop):
                raise OSError("Could not save face crop")
            coords.append([y1, y2, x1, x2])
            progress(70 + int(29 * (index + 1) / len(paths)))
        (stage / "coords.json").write_text(json.dumps(coords))
        (stage / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "avatar_id": avatar_id, "fps": 25, "face_size": size,
            "frame_count": len(paths), "model": "wav2lip", "rights_confirmed": True,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }))
        stage.rename(destination)
    progress(100)
