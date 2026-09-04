from dataclasses import replace
from pathlib import Path

import pytest

from scripts.dh_live_v1_provider import DH_LIVE_V1_COMMIT
from scripts.prepare_dh_live_v1_avatar import (
    DINET_WEIGHT_SHA256,
    DINET_WEIGHT_SIZE,
    PATCHED_SOURCE_TREE_SHA256,
)
from scripts.setup_dh_live_v1_runtime import (
    apply_dh_live_v1_patches,
    build_dh_live_v1_setup_plan,
    install_dh_live_v1_runtime,
)


def test_setup_plan_pins_source_python_checkpoint_and_lock(tmp_path: Path) -> None:
    plan = build_dh_live_v1_setup_plan(tmp_path / "runtime")

    assert plan.commit == DH_LIVE_V1_COMMIT
    assert plan.python_version == "3.10.20"
    assert plan.checkpoint_size_bytes == DINET_WEIGHT_SIZE
    assert plan.checkpoint_sha256 == DINET_WEIGHT_SHA256
    assert plan.patched_source_tree_sha256 == PATCHED_SOURCE_TREE_SHA256
    assert plan.lock_file.name == "dh-live-v1-macos-arm64-py310.txt"
    assert plan.lock_file.is_file()


def test_compatibility_patch_is_idempotent_and_removes_unsafe_iframe(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    render_model = repository / "talkingface/render_model_mini.py"
    html = repository / "web_demo/static/MiniLive.html"
    render_model.parent.mkdir(parents=True)
    html.parent.mkdir(parents=True)
    render_model.write_text(
        "x = torch.load(ckpt_path, map_location=device)\n"
        "y = random.sample(glob.glob(teeth_ref_img), 1)[0]\n",
        encoding="utf-8",
    )
    html.write_text(
        '<iframe id="screen2" src="dialog.html" frameborder="0" style="display: none;"></iframe>\n',
        encoding="utf-8",
    )

    apply_dh_live_v1_patches(repository)
    apply_dh_live_v1_patches(repository)

    patched_model = render_model.read_text(encoding="utf-8")
    patched_html = html.read_text(encoding="utf-8")
    assert "weights_only=True" in patched_model
    assert "sorted(glob.glob(teeth_ref_img))[0]" in patched_model
    assert "iframe" not in patched_html
    assert '<div id="screen2" style="display: none;"></div>' in patched_html


def test_install_rejects_modified_plan_before_external_commands(tmp_path: Path) -> None:
    plan = build_dh_live_v1_setup_plan(tmp_path / "runtime")

    with pytest.raises(ValueError, match="pinned definition"):
        install_dh_live_v1_runtime(replace(plan, commit="0" * 40))


def test_install_rejects_symlink_runtime_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "runtime"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symbolic link"):
        install_dh_live_v1_runtime(build_dh_live_v1_setup_plan(alias))
