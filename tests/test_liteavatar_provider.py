import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.liteavatar_provider as provider
from scripts.liteavatar_provider import (
    LiteAvatarRenderSpec,
    LiteAvatarRuntime,
    build_liteavatar_render_command,
)


def test_build_render_command_uses_official_cpu_cli() -> None:
    runtime = LiteAvatarRuntime(Path("/models/liteavatar/repository"), Path("/python"))
    spec = LiteAvatarRenderSpec(
        audio=Path("campaign/inputs/speech.wav"),
        avatar_dir=Path("/models/liteavatar/repository/data/sample_data/preload"),
        output=Path("campaign/runs/liteavatar/liteavatar-001.mp4"),
        rights_confirmed=True,
    )

    command = build_liteavatar_render_command(runtime, spec, result_dir=Path("/tmp/result"))

    assert command == [
        "/python",
        "/models/liteavatar/repository/lite_avatar.py",
        "--data_dir",
        "/models/liteavatar/repository/data/sample_data/preload",
        "--audio_file",
        str(Path("campaign/inputs/speech.wav").resolve()),
        "--result_dir",
        str(Path("/tmp/result").resolve()),
    ]


def test_build_render_command_rejects_missing_rights_and_commercial_scope() -> None:
    runtime = LiteAvatarRuntime(Path("repo"), Path("python"))
    unconfirmed = LiteAvatarRenderSpec(Path("speech.wav"), Path("avatar"), Path("out.mp4"), False)
    with pytest.raises(ValueError, match="rights"):
        build_liteavatar_render_command(runtime, unconfirmed, result_dir=Path("tmp"))

    commercial = LiteAvatarRenderSpec(
        Path("speech.wav"),
        Path("avatar"),
        Path("out.mp4"),
        True,
        usage_scope="commercial_marketing",
    )
    with pytest.raises(ValueError, match="license"):
        build_liteavatar_render_command(runtime, commercial, result_dir=Path("tmp"))


def test_build_render_command_rejects_unverified_custom_avatar_directory() -> None:
    runtime = LiteAvatarRuntime(Path("/models/liteavatar/repository"), Path("/python"))
    custom = LiteAvatarRenderSpec(
        Path("speech.wav"),
        Path("untrusted-avatar"),
        Path("out.mp4"),
        True,
    )

    with pytest.raises(ValueError, match="official sample"):
        build_liteavatar_render_command(runtime, custom, result_dir=Path("tmp"))


def test_diagnose_cli_reports_missing_runtime_as_json(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/liteavatar_provider.py",
            "diagnose",
            "--runtime-root",
            str(tmp_path / "runtime"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert payload["device"] == "unknown"
    assert any("missing Python" in issue for issue in payload["issues"])


@pytest.mark.parametrize(
    "error",
    (
        OSError("broken executable"),
        subprocess.TimeoutExpired(["python"], timeout=60),
    ),
)
def test_diagnose_converts_python_probe_failures_to_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    python = tmp_path / "python"
    python.write_text("broken", encoding="utf-8")
    runtime = LiteAvatarRuntime(tmp_path / "missing-repository", python)

    def fail_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    monkeypatch.setattr(provider.subprocess, "run", fail_probe)

    diagnostic = provider.inspect_liteavatar_runtime(runtime)

    assert diagnostic.ready is False
    assert "LiteAvatar Python dependency probe failed" in diagnostic.issues


def test_publish_never_overwrites_a_competing_output(tmp_path: Path) -> None:
    partial = tmp_path / "partial.mp4"
    output = tmp_path / "output.mp4"
    partial.write_bytes(b"new")
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        provider._publish_file_no_replace(partial, output)

    assert output.read_bytes() == b"existing"
    assert partial.read_bytes() == b"new"
