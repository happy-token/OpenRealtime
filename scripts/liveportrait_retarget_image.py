"""Run the official LivePortrait single-image retargeting editor without Gradio."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import torch


def _partial_fields(target_class, values):
    return target_class(**{key: value for key, value in values.items() if hasattr(target_class, key)})


def _apply_expression(delta, config):
    gaze_x = float(config["gaze_x"])
    gaze_y = float(config["gaze_y"])
    if gaze_x > 0:
        delta[0, 11, 0] += gaze_x * 0.0007
        delta[0, 15, 0] += gaze_x * 0.001
    else:
        delta[0, 11, 0] += gaze_x * 0.001
        delta[0, 15, 0] += gaze_x * 0.0007
    delta[0, 11, 1] += gaze_y * -0.001
    delta[0, 11, 1] += (-gaze_y / 2.0) * -0.001
    delta[0, 13, 1] += (-gaze_y / 2.0) * 0.0003
    delta[0, 15, 1] += gaze_y * -0.001
    delta[0, 15, 1] += (-gaze_y / 2.0) * -0.001
    delta[0, 16, 1] += (-gaze_y / 2.0) * 0.0003

    smile = float(config["smile"])
    delta[0, 20, 1] += smile * -0.01
    delta[0, 14, 1] += smile * -0.02
    delta[0, 17, 1] += smile * 0.0065
    delta[0, 17, 2] += smile * 0.003
    delta[0, 13, 1] += smile * -0.00275
    delta[0, 16, 1] += smile * -0.00275
    delta[0, 3, 1] += smile * -0.0035
    delta[0, 7, 1] += smile * -0.0035

    eyebrow = float(config["eyebrow"])
    if eyebrow > 0:
        delta[0, 1, 1] += eyebrow * 0.001
        delta[0, 2, 1] += eyebrow * -0.001
    else:
        delta[0, 1, 0] += eyebrow * -0.001
        delta[0, 2, 0] += eyebrow * 0.001
        delta[0, 1, 1] += eyebrow * 0.0003
        delta[0, 2, 1] += eyebrow * -0.0003
    delta[0, 5, 0] += -float(config["move_x"])
    delta[0, 5, 1] += float(config["move_y"])
    return delta


@torch.no_grad()
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()

    source_path = args.source.resolve()
    output_path = args.output.resolve()
    config_path = args.config.resolve()
    repository = args.repository.resolve()
    os.chdir(repository)
    sys.path.insert(0, str(repository))

    from src.config.argument_config import ArgumentConfig
    from src.config.crop_config import CropConfig
    from src.config.inference_config import InferenceConfig
    from src.live_portrait_pipeline import LivePortraitPipeline
    from src.utils.camera import get_rotation_matrix
    from src.utils.crop import paste_back, prepare_paste_back
    from src.utils.io import load_image_rgb, resize_to_limit
    from src.utils.retargeting_utils import calc_eye_close_ratio

    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime_args = ArgumentConfig()
    inference_config = _partial_fields(InferenceConfig, runtime_args.__dict__)
    crop_config = _partial_fields(CropConfig, runtime_args.__dict__)
    pipeline = LivePortraitPipeline(inference_cfg=inference_config, crop_cfg=crop_config)
    wrapper = pipeline.live_portrait_wrapper
    device = wrapper.device

    image = resize_to_limit(load_image_rgb(str(source_path)), 1280, 2)
    crop_info = pipeline.cropper.crop_source_image(image, pipeline.cropper.crop_cfg)
    if crop_info is None:
        raise RuntimeError("Source portrait NO face detected")
    source_landmarks = crop_info["lmk_crop"]
    source = wrapper.prepare_source(crop_info["img_crop_256x256"])
    source_info = wrapper.get_kp_info(source)
    source_rotation = get_rotation_matrix(source_info["pitch"], source_info["yaw"], source_info["roll"])
    driving_rotation = get_rotation_matrix(
        source_info["pitch"] + float(config["head_pitch"]),
        source_info["yaw"] + float(config["head_yaw"]),
        source_info["roll"] + float(config["head_roll"]),
    )
    source_feature = wrapper.extract_feature_3d(source)
    source_keypoints = wrapper.transform_keypoint(source_info).to(device)
    expression = _apply_expression(source_info["exp"].to(device), config)
    rotation = (driving_rotation @ source_rotation.permute(0, 2, 1)) @ source_rotation
    target_keypoints = float(config["zoom"]) * source_info["scale"].to(device) * (
        source_info["kp"].to(device) @ rotation + expression
    ) + source_info["t"].to(device)

    source_eye_ratio = round(float(calc_eye_close_ratio(source_landmarks[None]).mean()), 2)
    eye_ratio = max(0.0, min(0.8, source_eye_ratio + float(config["eye_open_delta"])))
    if eye_ratio != source_eye_ratio:
        combined_eye_ratio = wrapper.calc_combined_eye_ratio([[eye_ratio]], source_landmarks)
        target_keypoints += wrapper.retarget_eye(source_keypoints, combined_eye_ratio)
    if config["flag_stitching"]:
        target_keypoints = wrapper.stitching(source_keypoints, target_keypoints)
    output = wrapper.parse_output(wrapper.warp_decode(source_feature, source_keypoints, target_keypoints)["out"])[0]
    if config["flag_pasteback"]:
        mask = prepare_paste_back(inference_config.mask_crop, crop_info["M_c2o"], dsize=(image.shape[1], image.shape[0]))
        output = paste_back(output, crop_info["M_c2o"], image, mask)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), cv2.cvtColor(output, cv2.COLOR_RGB2BGR)):
        raise RuntimeError("LivePortrait failed to write the retargeted image")
    print(json.dumps({"output": str(output_path), "eye_ratio": eye_ratio}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
