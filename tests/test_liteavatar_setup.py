import hashlib
import io
from pathlib import Path

import pytest

from scripts.setup_liteavatar_runtime import (
    DOWNLOAD_TIMEOUT_SECONDS,
    _download_verified,
    apply_liteavatar_compatibility_patches,
    build_liteavatar_setup_plan,
)


def test_setup_plan_pins_source_weights_and_internal_evaluation_scope() -> None:
    plan = build_liteavatar_setup_plan(Path("models/liteavatar"))

    assert plan.repository_url == "https://github.com/HumanAIGC/lite-avatar.git"
    assert plan.commit == "5b7ec850945e03d56fb290b05fb68440c359fa86"
    assert plan.python_version == "3.10.20"
    assert plan.expected_weight_bytes == 1_302_291_222
    assert plan.code_license == "MIT"
    assert plan.model_license == "unspecified"
    assert plan.allowed_usage_scopes == ("internal_evaluation", "research")
    assert plan.lock_file.name == "liteavatar-macos-arm64-py310.txt"
    assert "onnxruntime==1.20.1" in plan.lock_file.read_text(encoding="utf-8")


def test_patch_removes_shell_calls_and_uses_safe_weight_loading(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "funasr_local/tasks").mkdir(parents=True)
    (repository / "lite_avatar.py").write_text(
        """
import os
        if os.path.exists(tmp_frame_dir):
            os.system(f'rm -rf {tmp_frame_dir}')
        os.mkdir(tmp_frame_dir)
        cmd = '/usr/bin/ffmpeg -r 30 -i {}/%05d.jpg -i {} -framerate 30 -c:v libx264 -pix_fmt yuv420p -b:v 5000k -strict experimental -loglevel error {}/test_demo.mp4 -y'.format(tmp_frame_dir, audio_file_path, result_dir)
        os.system(cmd)
""".strip(),
        encoding="utf-8",
    )
    (repository / "funasr_local/tasks/asr.py").write_text(
        "model_dict = torch.load(model_file, map_location=device)",
        encoding="utf-8",
    )
    (repository / "funasr_local/utils").mkdir(parents=True)
    (repository / "funasr_local/utils/asr_utils.py").write_text(
        "from modelscope.utils.logger import get_logger\n\nlogger = get_logger()\n",
        encoding="utf-8",
    )

    apply_liteavatar_compatibility_patches(repository)
    inference = (repository / "lite_avatar.py").read_text(encoding="utf-8")
    asr = (repository / "funasr_local/tasks/asr.py").read_text(encoding="utf-8")
    asr_utils = (repository / "funasr_local/utils/asr_utils.py").read_text(encoding="utf-8")
    assert "os.system" not in inference
    assert "subprocess.run([" in inference
    assert "shell=False" in inference
    assert "weights_only=True" in asr
    assert "modelscope" not in asr_utils

    apply_liteavatar_compatibility_patches(repository)


def test_verified_download_streams_with_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"verified model"
    seen: dict[str, object] = {}

    def open_stream(url: str, *, timeout: int) -> io.BytesIO:
        seen.update(url=url, timeout=timeout)
        return io.BytesIO(payload)

    monkeypatch.setattr("scripts.setup_liteavatar_runtime.urllib.request.urlopen", open_stream)
    destination = tmp_path / "model.pth"

    _download_verified(
        "https://models.example/model.pth",
        destination,
        hashlib.sha256(payload).hexdigest(),
    )

    assert destination.read_bytes() == payload
    assert seen == {
        "url": "https://models.example/model.pth",
        "timeout": DOWNLOAD_TIMEOUT_SECONDS,
    }
