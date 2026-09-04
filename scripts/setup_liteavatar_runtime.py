"""Install a pinned LiteAvatar CPU runtime on Apple Silicon."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.liteavatar_provider import (
    ALLOWED_USAGE_SCOPES,
    LITEAVATAR_COMMIT,
    LITEAVATAR_REPOSITORY_URL,
    LITEAVATAR_WEIGHT_FILES,
    LITEAVATAR_WEIGHT_HASHES,
    LiteAvatarRuntime,
    inspect_liteavatar_runtime,
)

MINIMUM_FREE_BYTES = 4 * 1024**3
MODEL_BASE_URL = "https://modelscope.cn/models/HumanAIGC-Engineering/LiteAvatarGallery/resolve/master/lite_avatar_weights"
SAMPLE_ZIP_SHA256 = "d1c77b2df48b7fd7f19e6eef52bc5107e3131dd9777162faf2576f9451f69d7b"
DOWNLOAD_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class LiteAvatarSetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    python_version: str
    minimum_free_bytes: int
    expected_weight_bytes: int
    code_license: str
    model_license: str
    allowed_usage_scopes: tuple[str, ...]
    lock_file: Path


def build_liteavatar_setup_plan(runtime_root: Path) -> LiteAvatarSetupPlan:
    return LiteAvatarSetupPlan(
        runtime_root=runtime_root,
        repository_url=LITEAVATAR_REPOSITORY_URL,
        commit=LITEAVATAR_COMMIT,
        python_version="3.10.20",
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        expected_weight_bytes=sum(LITEAVATAR_WEIGHT_FILES.values()),
        code_license="MIT",
        model_license="unspecified",
        allowed_usage_scopes=tuple(sorted(ALLOWED_USAGE_SCOPES)),
        lock_file=Path(__file__).with_name("locks") / "liteavatar-macos-arm64-py310.txt",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_required(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content and new not in old:
        return
    if old in content:
        path.write_text(content.replace(old, new), encoding="utf-8")
        return
    raise RuntimeError(f"LiteAvatar compatibility patch no longer applies: {path}: {old!r}")


def apply_liteavatar_compatibility_patches(repository: Path) -> None:
    inference = repository / "lite_avatar.py"
    _replace_required(inference, "import os\n", "import os\nimport shutil\nimport subprocess\n")
    _replace_required(
        inference,
        """        if os.path.exists(tmp_frame_dir):
            os.system(f'rm -rf {tmp_frame_dir}')
        os.mkdir(tmp_frame_dir)""",
        """        if os.path.exists(tmp_frame_dir):
            shutil.rmtree(tmp_frame_dir)
        os.mkdir(tmp_frame_dir)""",
    )
    _replace_required(
        inference,
        """        cmd = '/usr/bin/ffmpeg -r 30 -i {}/%05d.jpg -i {} -framerate 30 -c:v libx264 -pix_fmt yuv420p -b:v 5000k -strict experimental -loglevel error {}/test_demo.mp4 -y'.format(tmp_frame_dir, audio_file_path, result_dir)
        os.system(cmd)""",
        """        subprocess.run([
            os.environ.get('LITEAVATAR_FFMPEG', 'ffmpeg'), '-y', '-r', '30',
            '-i', f'{tmp_frame_dir}/%05d.jpg', '-i', audio_file_path,
            '-framerate', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-b:v', '5000k', '-strict', 'experimental', '-loglevel', 'error',
            f'{result_dir}/test_demo.mp4',
        ], check=True, shell=False)""",
    )
    asr = repository / "funasr_local/tasks/asr.py"
    content = asr.read_text(encoding="utf-8")
    if "weights_only=True" not in content:
        content = content.replace(
            "torch.load(model_file, map_location=device)",
            "torch.load(model_file, map_location=device, weights_only=True)",
        )
        asr.write_text(content, encoding="utf-8")
    asr_utils = repository / "funasr_local/utils/asr_utils.py"
    _replace_required(
        asr_utils,
        "from modelscope.utils.logger import get_logger\n\nlogger = get_logger()",
        "import logging\n\nlogger = logging.getLogger(__name__)",
    )


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def _python_matches(python: Path, expected: str) -> bool:
    if not python.is_file():
        return False
    try:
        probe = subprocess.run(
            [str(python), "-c", "import platform; print(platform.python_version())"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0 and probe.stdout.strip() == expected


def _capture(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, check=True, text=True).stdout


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required executable is missing: {name}")
    return executable


def _safe_extract_sample(repository: Path) -> None:
    archive = repository / "data/sample_data.zip"
    if _sha256(archive) != SAMPLE_ZIP_SHA256:
        raise RuntimeError("LiteAvatar sample archive hash mismatch")
    destination = repository / "data/sample_data"
    if destination.is_dir():
        return
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("LiteAvatar sample archive contains an unsafe path")
        bundle.extractall(destination)


def _download_verified(url: str, destination: Path, expected_hash: str) -> None:
    if destination.is_symlink():
        raise RuntimeError(f"Refusing LiteAvatar weight symlink: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with (
            urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
            temporary.open("wb") as destination_handle,
        ):
            shutil.copyfileobj(response, destination_handle, length=1024 * 1024)
        if _sha256(temporary) != expected_hash:
            raise RuntimeError(f"LiteAvatar download hash mismatch: {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_no_symlink_destination(destination: Path, *, root: Path) -> None:
    root = root.resolve()
    try:
        relative = destination.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            f"LiteAvatar weight destination escapes repository: {destination}"
        ) from error
    cursor = root
    if cursor.is_symlink() or destination.is_symlink():
        raise RuntimeError(f"Refusing LiteAvatar weight symlink: {destination}")
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            raise RuntimeError(f"Refusing LiteAvatar weight parent symlink: {cursor}")


def install_liteavatar_runtime(plan: LiteAvatarSetupPlan) -> LiteAvatarRuntime:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This setup command is limited to Apple Silicon macOS")
    root = plan.runtime_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < plan.minimum_free_bytes:
        raise RuntimeError(
            f"LiteAvatar setup requires at least {plan.minimum_free_bytes} free bytes"
        )
    git = _required_executable("git")
    uv = _required_executable("uv")
    repository = root / "repository"
    if not repository.exists():
        _run(
            [
                git,
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                plan.repository_url,
                str(repository),
            ]
        )
    elif not (repository / ".git").is_dir():
        raise RuntimeError(f"Existing LiteAvatar source is not a Git checkout: {repository}")
    _run([git, "-C", str(repository), "fetch", "--depth", "1", "origin", plan.commit])
    _run([git, "-C", str(repository), "checkout", "--detach", plan.commit])
    apply_liteavatar_compatibility_patches(repository)
    _safe_extract_sample(repository)

    environment = root / ".venv"
    python = environment / "bin/python"
    _run([uv, "python", "install", plan.python_version])
    if not _python_matches(python, plan.python_version):
        clear = ["--clear"] if environment.exists() else []
        _run([uv, "venv", *clear, "--python", plan.python_version, str(environment)])
    _run(
        [uv, "pip", "sync", "--python", str(python), str(plan.lock_file)],
        env={**os.environ, "UV_NO_CACHE": "1"},
    )

    remote_names = {
        Path("weights/model_1.onnx"): "model_1.onnx",
        Path(
            "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/model.pb"
        ): "model.pb",
        Path(
            "weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/lm/lm.pb"
        ): "lm.pb",
    }
    for relative, expected_size in LITEAVATAR_WEIGHT_FILES.items():
        destination = repository / relative
        _assert_no_symlink_destination(destination, root=repository)
        if (
            destination.is_file()
            and destination.stat().st_size == expected_size
            and _sha256(destination) == LITEAVATAR_WEIGHT_HASHES[relative]
        ):
            continue
        _download_verified(
            f"{MODEL_BASE_URL}/{remote_names[relative]}",
            destination,
            LITEAVATAR_WEIGHT_HASHES[relative],
        )

    runtime = LiteAvatarRuntime(repository, python)
    diagnostic = inspect_liteavatar_runtime(runtime)
    if not diagnostic.ready:
        raise RuntimeError("LiteAvatar verification failed: " + "; ".join(diagnostic.issues))
    return runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/liteavatar"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_liteavatar_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        payload["lock_file"] = str(plan.lock_file)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    runtime = install_liteavatar_runtime(plan)
    print(
        json.dumps(
            {"repository": str(runtime.repository), "python": str(runtime.python), "ready": True}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
