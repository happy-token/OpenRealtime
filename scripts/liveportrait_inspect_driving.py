"""Sample a driving video and report official LivePortrait lip-close ratios."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch


def _sample_frame_indexes(frame_count: int, sample_count: int) -> list[int]:
    if frame_count <= 0:
        return []
    count = min(frame_count, sample_count)
    return sorted({int(value) for value in np.linspace(0, frame_count - 1, count)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args()
    if not 8 <= args.samples <= 60:
        parser.error("--samples must be between 8 and 60")

    video = args.video.resolve()
    repository = args.repository.resolve()
    if not video.is_file():
        parser.error("--video must be an existing file")
    if not (repository / "src").is_dir():
        parser.error("--repository must be a LivePortrait checkout")

    os.chdir(repository)
    sys.path.insert(0, str(repository))
    from src.config.crop_config import CropConfig
    from src.utils.cropper import Cropper
    from src.utils.retargeting_utils import calc_lip_close_ratio

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the driving video")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    indexes = _sample_frame_indexes(frame_count, args.samples)
    ratios: list[float] = []
    try:
        with contextlib.redirect_stdout(sys.stderr):
            cropper = Cropper(
                crop_cfg=CropConfig(),
                flag_force_cpu=not (
                    torch.backends.mps.is_available() or torch.cuda.is_available()
                ),
            )
            for frame_index in indexes:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame_bgr = capture.read()
                if not ok:
                    continue
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                crop_info = cropper.crop_source_image(frame_rgb, cropper.crop_cfg)
                if crop_info is None:
                    continue
                ratio = float(calc_lip_close_ratio(crop_info["lmk_crop"][None]).item())
                if np.isfinite(ratio):
                    ratios.append(ratio)
    finally:
        capture.release()

    print(
        json.dumps(
            {
                "attempted_samples": len(indexes),
                "detected_samples": len(ratios),
                "ratios": ratios,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
