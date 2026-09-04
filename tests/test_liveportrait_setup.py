import hashlib
from pathlib import Path

import pytest

from scripts.setup_liveportrait_runtime import (
    _install_verified_weight,
    build_liveportrait_setup_plan,
)


def test_setup_plan_pins_official_source_and_only_downloads_human_weights() -> None:
    plan = build_liveportrait_setup_plan(Path("models/liveportrait"))

    assert plan.repository_url == "https://github.com/KlingAIResearch/LivePortrait.git"
    assert plan.commit == "9b294b3d0536135442ea73cb01e6cb3ca7029dd3"
    assert plan.model_revision == "82a4fa6735ca58432b6ce39301b4b9ee066dea47"
    assert plan.python_version == "3.10.20"
    assert plan.minimum_free_bytes == 12 * 1024**3
    assert plan.expected_weight_bytes == 658_941_445
    assert plan.lock_file.name == "liveportrait-macos-arm64-py310.txt"
    assert "torch==2.3.0" in plan.lock_file.read_text(encoding="utf-8")
    assert plan.weight_files == (
        "insightface/models/buffalo_l/2d106det.onnx",
        "insightface/models/buffalo_l/det_10g.onnx",
        "liveportrait/base_models/appearance_feature_extractor.pth",
        "liveportrait/base_models/motion_extractor.pth",
        "liveportrait/base_models/spade_generator.pth",
        "liveportrait/base_models/warping_module.pth",
        "liveportrait/landmark.onnx",
        "liveportrait/retargeting_models/stitching_retargeting_module.pth",
    )
    assert all("animals" not in weight_file for weight_file in plan.weight_files)


def test_verified_weight_install_rejects_symlink_destination(tmp_path: Path) -> None:
    root = tmp_path / "weights"
    root.mkdir()
    downloaded = tmp_path / "downloaded.pth"
    downloaded.write_bytes(b"verified")
    outside = tmp_path / "outside.pth"
    outside.write_bytes(b"keep")
    destination = root / "model.pth"
    destination.symlink_to(outside)

    with pytest.raises(RuntimeError, match="symbolic link"):
        _install_verified_weight(
            downloaded,
            destination,
            root=root,
            expected_size=len(b"verified"),
            expected_sha256=hashlib.sha256(b"verified").hexdigest(),
        )

    assert outside.read_bytes() == b"keep"
