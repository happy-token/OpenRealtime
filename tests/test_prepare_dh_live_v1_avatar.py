from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.prepare_dh_live_v1_avatar import (
    _snapshot_input_video,
    _source_tree_sha256,
    _validate_input_video,
    prepare_dh_live_v1_avatar,
)


def test_prepare_rejects_unconfirmed_rights_before_runtime_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rights"):
        prepare_dh_live_v1_avatar(
            runtime_root=tmp_path / "runtime",
            input_video=tmp_path / "input.mp4",
            output_bundle=tmp_path / "output",
            avatar_id="sample",
            rights_confirmed=False,
        )


@pytest.mark.parametrize("avatar_id", ["../escape", "Uppercase", "中文", "-sample", "a_b"])
def test_prepare_rejects_unsafe_avatar_ids(tmp_path: Path, avatar_id: str) -> None:
    with pytest.raises(ValueError, match="avatar_id"):
        prepare_dh_live_v1_avatar(
            runtime_root=tmp_path / "runtime",
            input_video=tmp_path / "input.mp4",
            output_bundle=tmp_path / "output",
            avatar_id=avatar_id,
            rights_confirmed=True,
        )


def test_source_hash_rejects_bytecode_cache_and_symlinks(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert _source_tree_sha256(repository)
    cache = repository / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-310.pyc").write_bytes(b"runtime cache")

    with pytest.raises(ValueError, match="bytecode caches"):
        _source_tree_sha256(repository)

    (cache / "module.cpython-310.pyc").unlink()
    cache.rmdir()
    (repository / "unsafe.py").symlink_to(repository / "module.py")
    with pytest.raises(ValueError, match="symbolic links"):
        _source_tree_sha256(repository)


def test_input_snapshot_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    alias = tmp_path / "alias.mp4"
    alias.symlink_to(source)

    with pytest.raises(ValueError, match="regular video"):
        _snapshot_input_video(alias, tmp_path / "snapshot.mp4")


def test_input_probe_rejects_zero_frame_rate_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        "scripts.prepare_dh_live_v1_avatar.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=(
                '{"streams":[{"width":720,"height":1280,'
                '"r_frame_rate":"0/0","nb_read_frames":"78"}]}'
            )
        ),
    )

    with pytest.raises(ValueError, match="720x1280"):
        _validate_input_video(video)
