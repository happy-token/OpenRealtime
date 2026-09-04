import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.liveportrait_provider as provider
from scripts.liveportrait_provider import (
    LivePortraitRenderSpec,
    LivePortraitRuntime,
    build_liveportrait_render_command,
    classify_driving_mouth_motion,
    inspect_driving_video,
    inspect_liveportrait_runtime,
    run_liveportrait_render,
)


def test_closed_mouth_classifier_accepts_small_natural_variation() -> None:
    result = classify_driving_mouth_motion(
        [0.002, 0.004, 0.003, 0.007, 0.004, 0.006, 0.003, 0.005]
    )

    assert result.eligible is True
    assert result.reason is None


def test_closed_mouth_classifier_rejects_sustained_open_mouth() -> None:
    result = classify_driving_mouth_motion(
        [0.025, 0.034, 0.029, 0.041, 0.032, 0.038, 0.027, 0.035]
    )

    assert result.eligible is False
    assert result.reason == "参考视频中嘴部持续张开，请改用自然闭嘴的非语言表演"


def test_closed_mouth_classifier_rejects_talking_motion() -> None:
    result = classify_driving_mouth_motion(
        [0.003, 0.052, 0.004, 0.091, 0.006, 0.073, 0.003, 0.061, 0.004, 0.005]
    )

    assert result.eligible is False
    assert result.reason == "参考视频包含明显说话口型或大幅嘴部运动，请重新录制闭嘴表演"


def test_driving_inspection_rejects_video_shorter_than_five_seconds(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    driving = tmp_path / "short.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=4.8:r=10",
            "-an",
            str(driving),
        ],
        check=True,
        capture_output=True,
    )

    result = inspect_driving_video(
        LivePortraitRuntime(Path("/unused/repository"), Path(sys.executable)),
        driving,
        ffprobe=Path(ffprobe),
    )

    assert result.eligible is False
    assert result.reason == "自定义参考视频需为 5–15 秒"
    assert result.duration_seconds == pytest.approx(4.8, abs=0.1)


def test_driving_inspection_uses_landmark_ratios_for_eligible_video(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    driving = tmp_path / "natural.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=5.2:r=10",
            "-an",
            str(driving),
        ],
        check=True,
        capture_output=True,
    )
    analyzer = tmp_path / "analyzer.py"
    analyzer.write_text(
        "import json; print(json.dumps({'ratios': [0.003, 0.005, 0.004, 0.0045], "
        "'attempted_samples': 4, 'detected_samples': 4}))",
        encoding="utf-8",
    )

    result = inspect_driving_video(
        LivePortraitRuntime(tmp_path / "repository", Path(sys.executable)),
        driving,
        ffprobe=Path(ffprobe),
        analyzer_script=analyzer,
    )

    assert result.eligible is True
    assert result.sample_count == 4
    assert result.median_ratio == pytest.approx(0.00425)


def test_driving_inspection_rejects_video_without_consistently_detected_face(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    driving = tmp_path / "missing-face.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=16x16:d=5:r=10", "-an", str(driving)],
        check=True,
        capture_output=True,
    )
    analyzer = tmp_path / "analyzer.py"
    analyzer.write_text(
        "import json; print(json.dumps({'ratios': [0.04, 0.05], "
        "'attempted_samples': 24, 'detected_samples': 2}))",
        encoding="utf-8",
    )

    result = inspect_driving_video(
        LivePortraitRuntime(tmp_path / "repository", Path(sys.executable)),
        driving,
        ffprobe=Path(ffprobe),
        analyzer_script=analyzer,
    )

    assert result.eligible is False
    assert result.reason == "参考视频中未持续检测到清晰单人脸，请重新录制"


def test_build_liveportrait_render_command_uses_official_cli_and_campaign_output() -> None:
    runtime = LivePortraitRuntime(
        repository=Path("/models/liveportrait/repository"),
        python=Path("/models/liveportrait/.venv/bin/python"),
    )
    spec = LivePortraitRenderSpec(
        source=Path("campaign/inputs/portrait.jpg"),
        driving=Path("campaign/inputs/driving.mp4"),
        output_dir=Path("campaign/runs/liveportrait/raw"),
        rights_confirmed=True,
    )

    assert build_liveportrait_render_command(runtime, spec) == [
        "/models/liveportrait/.venv/bin/python",
        "/models/liveportrait/repository/inference.py",
        "-s",
        "campaign/inputs/portrait.jpg",
        "-d",
        "campaign/inputs/driving.mp4",
        "-o",
        "campaign/runs/liveportrait/raw",
    ]


def test_build_liveportrait_render_command_requires_rights_confirmation() -> None:
    runtime = LivePortraitRuntime(Path("repo"), Path("python"))
    spec = LivePortraitRenderSpec(
        source=Path("portrait.jpg"),
        driving=Path("driving.mp4"),
        output_dir=Path("output"),
        rights_confirmed=False,
    )

    with pytest.raises(ValueError, match="rights"):
        build_liveportrait_render_command(runtime, spec)


def test_build_liveportrait_render_command_applies_supported_opentalking_fields_only() -> None:
    runtime = LivePortraitRuntime(Path("repo"), Path("python"))
    spec = LivePortraitRenderSpec(
        source=Path("portrait.jpg"),
        driving=Path("driving.mp4"),
        output_dir=Path("output"),
        rights_confirmed=True,
        runtime_config={
            "driving_multiplier": 0.8,
            "animation_region": "all",
            "flag_stitching": True,
            "flag_pasteback": False,
            "flag_normalize_lip": True,
            "flag_relative_motion": False,
            "mouth_open_multiplier": 2.0,
        },
    )

    command = build_liveportrait_render_command(runtime, spec)
    assert command[-8:] == [
        "--driving-multiplier", "0.8",
        "--animation-region", "all",
        "--flag-stitching",
        "--no-flag-pasteback",
        "--flag-normalize-lip",
        "--no-flag-relative-motion",
    ]
    assert "mouth_open_multiplier" not in " ".join(command)


def _configure_fake_contract(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    weight_bytes: bytes = b"model",
) -> None:
    fake_weight = repository / "pretrained_weights/weights/model.pth"
    fake_weight.parent.mkdir(parents=True, exist_ok=True)
    fake_weight.write_bytes(weight_bytes)
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "add", "inference.py"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/liveportrait.git"],
        cwd=repository,
        check=True,
    )
    relative_weight = Path("weights/model.pth")
    monkeypatch.setattr(provider, "HUMAN_WEIGHT_FILES", {relative_weight: len(weight_bytes)})
    monkeypatch.setattr(
        provider,
        "HUMAN_WEIGHT_HASHES",
        {relative_weight: hashlib.sha256(weight_bytes).hexdigest()},
    )
    monkeypatch.setattr(
        provider, "LIVEPORTRAIT_REPOSITORY_URL", "https://example.com/liveportrait.git"
    )
    monkeypatch.setattr(provider, "LIVEPORTRAIT_COMMIT", commit)
    monkeypatch.setattr(provider, "REQUIRED_PYTHON", sys.version_info[:3])


def test_inspect_liveportrait_runtime_accepts_verified_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "inference.py").write_text(
        "import argparse; argparse.ArgumentParser().parse_args()", encoding="utf-8"
    )
    _configure_fake_contract(repository, monkeypatch)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    diagnostic = inspect_liveportrait_runtime(
        LivePortraitRuntime(repository=repository, python=Path(sys.executable)),
        ffmpeg=Path(ffmpeg),
    )

    assert diagnostic.ready is True
    assert diagnostic.issues == ()
    assert diagnostic.weights_bytes == 5
    assert diagnostic.device in {"mps", "cuda", "cpu"}


def test_inspect_liveportrait_runtime_rejects_same_size_tampered_weight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "inference.py").write_text("", encoding="utf-8")
    _configure_fake_contract(repository, monkeypatch)
    (repository / "pretrained_weights/weights/model.pth").write_bytes(b"evil!")

    diagnostic = inspect_liveportrait_runtime(
        LivePortraitRuntime(repository=repository, python=Path(sys.executable)),
        ffmpeg=Path(shutil.which("ffmpeg") or "/missing/ffmpeg"),
    )

    assert diagnostic.ready is False
    assert any("hash" in issue for issue in diagnostic.issues)


def test_liveportrait_diagnose_cli_reports_machine_readable_missing_runtime(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/liveportrait_provider.py",
            "diagnose",
            "--runtime-root",
            str(runtime_root),
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[1],
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert payload["device"] == "unknown"
    assert payload["weights_bytes"] == 658_941_445
    assert any("missing Python executable" in issue for issue in payload["issues"])
    assert any("missing official inference script" in issue for issue in payload["issues"])


def test_run_liveportrait_render_verifies_and_atomically_promotes_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    fixture = tmp_path / "fixture.mp4"
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=0.2:r=25",
            "-an",
            str(fixture),
        ],
        check=True,
        capture_output=True,
    )
    inference = repository / "inference.py"
    inference.write_text(
        f"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-s")
parser.add_argument("-d")
parser.add_argument("-o")
args = parser.parse_args()
output = Path(args.o)
output.mkdir(parents=True, exist_ok=True)
(output / f"{{Path(args.s).stem}}--{{Path(args.d).stem}}.mp4").write_bytes(
    Path({str(fixture)!r}).read_bytes()
)
""".strip(),
        encoding="utf-8",
    )
    _configure_fake_contract(repository, monkeypatch)
    source = tmp_path / "portrait.jpg"
    driving = tmp_path / "idle.mp4"
    source.write_bytes(b"portrait")
    driving.write_bytes(b"driving")
    output_dir = tmp_path / "output"

    result = run_liveportrait_render(
        LivePortraitRuntime(repository=repository, python=Path(sys.executable)),
        LivePortraitRenderSpec(source, driving, output_dir, rights_confirmed=True),
        ffmpeg=Path(ffmpeg),
        ffprobe=Path(ffprobe),
    )

    assert result.output_path == output_dir / "portrait--idle.mp4"
    assert result.output_path.stat().st_size > 0
    assert result.render_seconds >= 0
    assert not list(output_dir.glob("*.partial.mp4"))


def test_run_liveportrait_stages_shell_metacharacter_paths_under_fixed_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    fixture = tmp_path / "fixture.mp4"
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=0.2:r=25",
            "-an",
            str(fixture),
        ],
        check=True,
        capture_output=True,
    )
    inference = repository / "inference.py"
    inference.write_text(
        f"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-s")
parser.add_argument("-d")
parser.add_argument("-o")
args = parser.parse_args()
assert Path(args.s).name == "source.jpg"
assert Path(args.d).name == "driving.mp4"
assert all(character not in args.o for character in ";$()`")
output = Path(args.o)
output.mkdir(parents=True, exist_ok=True)
(output / "source--driving.mp4").write_bytes(Path({str(fixture)!r}).read_bytes())
""".strip(),
        encoding="utf-8",
    )
    _configure_fake_contract(repository, monkeypatch)
    source = tmp_path / "portrait;$(touch injected).jpg"
    driving = tmp_path / "idle`touch injected`.mp4"
    source.write_bytes(b"portrait")
    driving.write_bytes(b"driving")

    result = run_liveportrait_render(
        LivePortraitRuntime(repository=repository, python=Path(sys.executable)),
        LivePortraitRenderSpec(source, driving, tmp_path / "output", rights_confirmed=True),
        ffmpeg=Path(ffmpeg),
        ffprobe=Path(ffprobe),
    )

    assert result.output_path.is_file()
    assert not (tmp_path / "injected").exists()


def test_publish_never_overwrites_a_competing_output(tmp_path: Path) -> None:
    partial = tmp_path / "partial.mp4"
    output = tmp_path / "output.mp4"
    partial.write_bytes(b"new")
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        provider._publish_file_no_replace(partial, output)

    assert output.read_bytes() == b"existing"
    assert partial.read_bytes() == b"new"
