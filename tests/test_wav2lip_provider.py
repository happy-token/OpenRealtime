import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.wav2lip_provider as provider
from scripts.wav2lip_provider import (
    Wav2LipRenderSpec,
    Wav2LipRuntime,
    build_wav2lip_render_command,
    inspect_wav2lip_runtime,
    run_wav2lip_render,
)


def test_build_render_command_uses_official_cli_and_offline_inputs() -> None:
    runtime = Wav2LipRuntime(
        repository=Path("/models/wav2lip/repository"),
        python=Path("/models/wav2lip/.venv/bin/python"),
    )
    spec = Wav2LipRenderSpec(
        face=Path("campaign/runs/liveportrait/liveportrait-001.mp4"),
        audio=Path("campaign/inputs/speech.wav"),
        output=Path("campaign/runs/wav2lip/wav2lip-offline-001.mp4"),
        rights_confirmed=True,
        device="mps",
    )

    assert build_wav2lip_render_command(runtime, spec) == [
        "/models/wav2lip/.venv/bin/python",
        "/models/wav2lip/repository/inference.py",
        "--checkpoint_path",
        "/models/wav2lip/repository/checkpoints/wav2lip.pth",
        "--face",
        "campaign/runs/liveportrait/liveportrait-001.mp4",
        "--audio",
        "campaign/inputs/speech.wav",
        "--outfile",
        "campaign/runs/wav2lip/wav2lip-offline-001.mp4",
    ]


def test_build_render_command_requires_rights_and_wav_audio() -> None:
    runtime = Wav2LipRuntime(Path("repo"), Path("python"))
    unconfirmed = Wav2LipRenderSpec(
        Path("face.mp4"), Path("speech.wav"), Path("out.mp4"), False, "cpu"
    )
    with pytest.raises(ValueError, match="rights"):
        build_wav2lip_render_command(runtime, unconfirmed)

    unsafe_audio = Wav2LipRenderSpec(
        Path("face.mp4"), Path("speech.mp3"), Path("out.mp4"), True, "cpu"
    )
    with pytest.raises(ValueError, match="WAV"):
        build_wav2lip_render_command(runtime, unsafe_audio)

    commercial = Wav2LipRenderSpec(
        Path("face.mp4"),
        Path("speech.wav"),
        Path("out.mp4"),
        True,
        "cpu",
        usage_scope="commercial_marketing",
    )
    with pytest.raises(ValueError, match="non-commercial"):
        build_wav2lip_render_command(runtime, commercial)


def test_build_render_command_can_bypass_detection_with_a_validated_face_box() -> None:
    runtime = Wav2LipRuntime(Path("repo"), Path("python"))
    spec = Wav2LipRenderSpec(
        Path("face.mp4"),
        Path("speech.wav"),
        Path("out.mp4"),
        True,
        "mps",
        face_box=(450, 660, 255, 455),
    )

    command = build_wav2lip_render_command(runtime, spec)

    assert command[-5:] == ["--box", "450", "660", "255", "455"]


def _configure_fake_runtime(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative_weight = Path("checkpoints/wav2lip.pth")
    weight = repository / relative_weight
    weight.parent.mkdir(parents=True, exist_ok=True)
    weight.write_bytes(b"model")
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
        ["git", "remote", "add", "origin", "https://example.com/wav2lip.git"],
        cwd=repository,
        check=True,
    )
    monkeypatch.setattr(provider, "WAV2LIP_WEIGHT_FILES", {relative_weight: 5})
    monkeypatch.setattr(
        provider,
        "WAV2LIP_WEIGHT_HASHES",
        {relative_weight: hashlib.sha256(b"model").hexdigest()},
    )
    monkeypatch.setattr(provider, "WAV2LIP_REPOSITORY_URL", "https://example.com/wav2lip.git")
    monkeypatch.setattr(provider, "WAV2LIP_COMMIT", commit)
    monkeypatch.setattr(provider, "WAV2LIP_PATCH_DIFF_SHA256", hashlib.sha256(b"").hexdigest())
    monkeypatch.setattr(provider, "REQUIRED_PYTHON", sys.version_info[:3])


def test_inspect_runtime_accepts_complete_verified_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "inference.py").write_text(
        "import argparse; argparse.ArgumentParser().parse_args()", encoding="utf-8"
    )
    _configure_fake_runtime(repository, monkeypatch)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    diagnostic = inspect_wav2lip_runtime(
        Wav2LipRuntime(repository, Path(sys.executable)), ffmpeg=Path(ffmpeg)
    )

    assert diagnostic.ready is True
    assert diagnostic.issues == ()
    assert diagnostic.weights_bytes == 5
    assert diagnostic.device in {"mps", "cuda", "cpu"}


def test_diagnose_cli_reports_machine_readable_missing_runtime(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/wav2lip_provider.py",
            "diagnose",
            "--runtime-root",
            str(tmp_path / "runtime"),
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
    assert any("missing Python executable" in issue for issue in payload["issues"])


def test_run_render_passes_mps_override_and_returns_verified_output(
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
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--checkpoint_path")
parser.add_argument("--face")
parser.add_argument("--audio")
parser.add_argument("--outfile")
args = parser.parse_args()
assert os.environ["WAV2LIP_DEVICE_OVERRIDE"] == "mps"
Path(args.outfile).write_bytes(Path({str(fixture)!r}).read_bytes())
""".strip(),
        encoding="utf-8",
    )
    _configure_fake_runtime(repository, monkeypatch)
    face = tmp_path / "face.mp4"
    audio = tmp_path / "speech.wav"
    face.write_bytes(b"face")
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"

    lock_operations: list[int] = []
    original_flock = provider.fcntl.flock

    def recording_flock(file_descriptor: int, operation: int) -> None:
        lock_operations.append(operation)
        original_flock(file_descriptor, operation)

    monkeypatch.setattr(provider.fcntl, "flock", recording_flock)

    result = run_wav2lip_render(
        Wav2LipRuntime(repository, Path(sys.executable)),
        Wav2LipRenderSpec(face, audio, output, True, "mps"),
        ffmpeg=Path(ffmpeg),
        ffprobe=Path(ffprobe),
    )

    assert result.output_path == output.resolve()
    assert result.output_path.stat().st_size > 0
    assert result.render_seconds >= 0
    assert lock_operations == [provider.fcntl.LOCK_EX, provider.fcntl.LOCK_UN]


def test_publish_never_overwrites_a_competing_output(tmp_path: Path) -> None:
    partial = tmp_path / "partial.mp4"
    output = tmp_path / "output.mp4"
    partial.write_bytes(b"new")
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        provider._publish_file_no_replace(partial, output)

    assert output.read_bytes() == b"existing"
    assert partial.read_bytes() == b"new"
