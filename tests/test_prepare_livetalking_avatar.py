from pathlib import Path

import pytest

from scripts.prepare_livetalking_avatar import (
    AvatarPreparationPlan,
    build_avatar_preparation_plan,
)


def test_avatar_plan_uses_fixed_face_box_and_256_pixel_default_model(tmp_path: Path) -> None:
    source = tmp_path / "motion.mp4"
    source.write_bytes(b"video")

    plan = build_avatar_preparation_plan(
        source,
        avatar_root=tmp_path / "avatars/shuchang",
        face_box=(450, 660, 255, 455),
        rights_confirmed=True,
    )

    assert plan.source == source.resolve()
    assert plan.face_box == (450, 660, 255, 455)
    assert plan.face_size == 256
    assert plan.frames_per_second == 25
    assert plan.rights_confirmed is True


def test_avatar_plan_rejects_unconfirmed_rights(tmp_path: Path) -> None:
    source = tmp_path / "motion.mp4"
    source.write_bytes(b"video")

    with pytest.raises(ValueError, match="rights"):
        build_avatar_preparation_plan(
            source,
            avatar_root=tmp_path / "avatar",
            face_box=(1, 2, 3, 4),
            rights_confirmed=False,
        )


def test_prepare_rechecks_rights_on_a_directly_constructed_plan(tmp_path: Path) -> None:
    source = tmp_path / "motion.mp4"
    source.write_bytes(b"video")
    with pytest.raises(ValueError, match="rights"):
        AvatarPreparationPlan(
            source=source,
            avatar_root=tmp_path / "avatar",
            face_box=(1, 2, 3, 4),
            face_size=256,
            frames_per_second=25,
            rights_confirmed=False,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("face_box", (-1, 2, 3, 4)), ("face_size", 1024), ("frames_per_second", 0)),
)
def test_direct_avatar_plan_construction_enforces_all_invariants(
    tmp_path: Path, field: str, value: object
) -> None:
    source = tmp_path / "motion.mp4"
    source.write_bytes(b"video")
    values = {
        "source": source,
        "avatar_root": tmp_path / "avatar",
        "face_box": (1, 2, 3, 4),
        "face_size": 256,
        "frames_per_second": 25,
        "rights_confirmed": True,
    }
    values[field] = value
    with pytest.raises(ValueError):
        AvatarPreparationPlan(**values)
