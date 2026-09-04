import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.livetalking_provider import (
    LiveTalkingRuntime,
    _inspect_avatar,
    build_livetalking_server_command,
    build_livetalking_server_environment,
)


def test_build_server_command_uses_preprocessed_avatar_and_small_streaming_batch() -> None:
    runtime = LiveTalkingRuntime(
        repository=Path("/models/livetalking/repository"),
        python=Path("/models/livetalking/.venv/bin/python"),
    )

    command = build_livetalking_server_command(
        runtime,
        avatar_id="shuchang",
        port=8010,
        batch_size=4,
        inference_stride=2,
    )

    assert command == [
        "/models/livetalking/.venv/bin/python",
        "/models/livetalking/repository/app.py",
        "--config",
        "",
        "--transport",
        "webrtc",
        "--model",
        "wav2lip",
        "--avatar_id",
        "shuchang",
        "--batch_size",
        "4",
        "--modelres",
        "256",
        "--modelfile",
        "/models/livetalking/repository/models/wav2lip256.pth",
        "--wav2lip_inference_stride",
        "2",
        "--listenport",
        "8010",
        "--stun",
        "",
    ]


@pytest.mark.parametrize("inference_stride", (0, 3))
def test_server_command_rejects_unsupported_wav2lip_inference_stride(
    inference_stride: int,
) -> None:
    runtime = LiveTalkingRuntime(Path("repo"), Path("python"))

    with pytest.raises(ValueError, match="inference_stride"):
        build_livetalking_server_command(
            runtime,
            avatar_id="shuchang",
            port=8010,
            batch_size=4,
            inference_stride=inference_stride,
        )


@pytest.mark.parametrize("model_size", (96, 256))
def test_build_server_environment_is_loopback_only_with_selected_model_size(
    model_size: int,
) -> None:
    environment = build_livetalking_server_environment(
        {"PATH": "/usr/bin"},
        model_size=model_size,
    )

    assert environment["LIVETALKING_BIND_HOST"] == "127.0.0.1"
    assert environment["LIVETALKING_ALLOWED_ORIGINS"] == (
        "http://127.0.0.1:3010,http://localhost:3010"
    )
    assert environment["LIVETALKING_ENABLE_MANAGEMENT_ROUTES"] == "0"
    assert environment["LIVETALKING_WAV2LIP_MODEL_SIZE"] == str(model_size)
    assert environment["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
    assert environment["PATH"] == "/usr/bin"


def test_server_command_rejects_commercial_marketing_use() -> None:
    runtime = LiveTalkingRuntime(Path("repo"), Path("python"))

    with pytest.raises(ValueError, match="non-commercial"):
        build_livetalking_server_command(
            runtime,
            avatar_id="shuchang",
            port=8010,
            usage_scope="commercial_marketing",
        )


@pytest.mark.parametrize("rights", (None, False, "true"))
def test_avatar_inspection_rejects_missing_false_or_non_boolean_rights(
    tmp_path: Path, rights: object
) -> None:
    repository = tmp_path / "repository"
    avatar = repository / "data/avatars/shuchang"
    full = avatar / "full_imgs"
    face = avatar / "face_imgs"
    full.mkdir(parents=True)
    face.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    def png(width: int, height: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)

    (full / "00000000.png").write_bytes(png(720, 1280))
    (face / "00000000.png").write_bytes(png(256, 256))
    (avatar / "coords.json").write_text("[[1,101,2,102]]\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "avatar_id": "shuchang",
        "source": str(source),
        "source_sha256": hashlib.sha256(b"source").hexdigest(),
        "frame_count": 1,
        "fps": 25,
        "face_box": [1, 101, 2, 102],
        "face_size": 256,
    }
    if rights is not None:
        manifest["rights_confirmed"] = rights
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    frame_count, issues = _inspect_avatar(repository, "shuchang", python=Path(sys.executable))

    assert frame_count is None
    assert issues == ["invalid preprocessed avatar manifest: shuchang"]


def test_avatar_inspection_rejects_frames_the_runtime_decoder_cannot_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    avatar = repository / "data/avatars/shuchang"
    full = avatar / "full_imgs"
    face = avatar / "face_imgs"
    full.mkdir(parents=True)
    face.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    truncated = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 96, 96)
    (full / "00000000.png").write_bytes(truncated)
    (face / "00000000.png").write_bytes(truncated)
    (avatar / "coords.json").write_text("[[1,95,1,95]]\n", encoding="utf-8")
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "avatar_id": "shuchang",
                "source": str(source),
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "frame_count": 1,
                "fps": 25,
                "face_box": [1, 95, 1, 95],
                "face_size": 256,
                "rights_confirmed": True,
            }
        ),
        encoding="utf-8",
    )

    def reject_decode(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("scripts.livetalking_provider.subprocess.run", reject_decode)

    frame_count, issues = _inspect_avatar(
        repository,
        "shuchang",
        python=Path("/verified/runtime/python"),
    )

    assert frame_count is None
    assert issues == ["invalid preprocessed avatar manifest: shuchang"]
