"""Install a pinned, compatibility-patched Wav2Lip runtime on Apple Silicon."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.wav2lip_provider import (
    WAV2LIP_COMMIT,
    WAV2LIP_PATCH_DIFF_SHA256,
    WAV2LIP_REPOSITORY_URL,
    WAV2LIP_WEIGHT_FILES,
    WAV2LIP_WEIGHT_HASHES,
    Wav2LipRuntime,
    _sha256,
    inspect_wav2lip_runtime,
)

MINIMUM_FREE_BYTES = 6 * 1024**3
MINIMUM_REPAIR_FREE_BYTES = 2 * 1024**3
WAV2LIP_MODEL_REPOSITORY = "numz/wav2lip_studio"
WAV2LIP_MODEL_REVISION = "837b372bdf9a4ba030b4079bc0aaa7097adc1d17"
S3FD_MODEL_REPOSITORY = "ByteDance/LatentSync"
S3FD_MODEL_REVISION = "405eda8eab9f65c1a6e0c292a5dee5a08089e2ae"


@dataclass(frozen=True)
class Wav2LipSetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    python_version: str
    minimum_free_bytes: int
    expected_weight_bytes: int
    lock_file: Path
    weight_files: tuple[str, ...]
    model_revisions: tuple[str, ...]


def build_wav2lip_setup_plan(runtime_root: Path) -> Wav2LipSetupPlan:
    return Wav2LipSetupPlan(
        runtime_root=runtime_root,
        repository_url=WAV2LIP_REPOSITORY_URL,
        commit=WAV2LIP_COMMIT,
        python_version="3.10.20",
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        expected_weight_bytes=sum(WAV2LIP_WEIGHT_FILES.values()),
        lock_file=Path(__file__).with_name("locks") / "wav2lip-macos-arm64-py310.txt",
        weight_files=tuple(path.as_posix() for path in WAV2LIP_WEIGHT_FILES),
        model_revisions=(WAV2LIP_MODEL_REVISION, S3FD_MODEL_REVISION),
    )


def _replace_required(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    if new in content and new not in old:
        return
    if old in content:
        path.write_text(content.replace(old, new), encoding="utf-8")
        return
    if new not in content:
        raise RuntimeError(f"Wav2Lip compatibility patch no longer applies: {path}: {old!r}")


def apply_wav2lip_compatibility_patches(repository: Path) -> None:
    """Apply the reviewed modern-Python, safe-FFmpeg, and MPS patch set."""

    for relative_path in (
        Path("inference.py"),
        Path("face_detection/detection/sfd/sfd_detector.py"),
    ):
        path = repository / relative_path
        content = path.read_text(encoding="utf-8")
        if "weights_only=False" in content:
            path.write_text(
                content.replace("weights_only=False", "weights_only=True"), encoding="utf-8"
            )

    _replace_required(
        repository / "audio.py",
        "librosa.core.load(path, sr=sr)",
        "librosa.load(path, sr=sr)",
    )
    _replace_required(
        repository / "audio.py",
        "    librosa.output.write_wav(path, wav, sr=sr)",
        "    import soundfile as sf\n    sf.write(path, wav, sr)",
    )
    _replace_required(
        repository / "audio.py",
        "librosa.filters.mel(hp.sample_rate, hp.n_fft, n_mels=hp.num_mels,",
        "librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft, n_mels=hp.num_mels,",
    )
    _replace_required(
        repository / "face_detection/utils.py",
        "dtype=np.int)",
        "dtype=int)",
    )
    _replace_required(
        repository / "face_detection/detection/core.py",
        "if 'cpu' not in device and 'cuda' not in device:",
        "if 'cpu' not in device and 'cuda' not in device and 'mps' not in device:",
    )
    _replace_required(
        repository / "face_detection/detection/sfd/sfd_detector.py",
        "torch.load(path_to_detector)",
        "torch.load(path_to_detector, weights_only=True)",
    )
    inference = repository / "inference.py"
    _replace_required(
        inference,
        "device = 'cuda' if torch.cuda.is_available() else 'cpu'",
        (
            "_device_override = os.environ.get('WAV2LIP_DEVICE_OVERRIDE', '').strip()\n"
            "if _device_override in ('mps', 'cpu', 'cuda'):\n"
            "\tdevice = _device_override\n"
            "else:\n"
            "\tdevice = 'cuda' if torch.cuda.is_available() else 'cpu'"
        ),
    )
    _replace_required(
        inference,
        "torch.load(checkpoint_path)",
        "torch.load(checkpoint_path, weights_only=True)",
    )
    _replace_required(
        inference,
        "map_location=lambda storage, loc: storage)",
        "map_location=lambda storage, loc: storage, weights_only=True)",
    )
    _replace_required(
        inference,
        "args.face.split('.')[1]",
        "os.path.splitext(args.face)[1].lower().lstrip('.')",
    )
    _replace_required(inference, "cv2.cv2.ROTATE_90_CLOCKWISE", "cv2.ROTATE_90_CLOCKWISE")
    _replace_required(
        inference,
        (
            "command = 'ffmpeg -y -i {} -i {} -strict -2 -q:v 1 {}'.format("
            "args.audio, 'temp/result.avi', args.outfile)\n"
            "\tsubprocess.call(command, shell=platform.system() != 'Windows')"
        ),
        (
            "subprocess.run([\n"
            "\t\t'ffmpeg', '-y', '-i', args.audio, '-i', 'temp/result.avi',\n"
            "\t\t'-strict', '-2', '-q:v', '1', args.outfile,\n"
            "\t], check=True)"
        ),
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


def _install_verified_weight(
    downloaded: Path,
    destination: Path,
    *,
    root: Path,
    expected_sha256: str,
) -> None:
    root = root.resolve()
    _assert_no_symlink_destination(destination, root=root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", dir=destination.parent, delete=False
    ) as temporary_handle:
        temporary = Path(temporary_handle.name)
    try:
        shutil.copyfile(downloaded, temporary)
        if _sha256(temporary) != expected_sha256:
            raise RuntimeError(f"Downloaded weight hash mismatch: {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_no_symlink_destination(destination: Path, *, root: Path) -> None:
    root = root.resolve()
    try:
        relative = destination.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"Weight destination escapes repository: {destination}") from error
    cursor = root
    if cursor.is_symlink() or destination.is_symlink():
        raise RuntimeError(f"Weight destination must not be a symbolic link: {destination}")
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            raise RuntimeError(f"Weight parent must not be a symbolic link: {cursor}")


def _runtime_materialized(runtime_root: Path) -> bool:
    repository = runtime_root / "repository"
    python = runtime_root / ".venv/bin/python"
    return (
        (repository / "inference.py").is_file()
        and python.is_file()
        and all(
            (repository / relative_path).is_file()
            and (repository / relative_path).stat().st_size == size
            and _sha256(repository / relative_path) == WAV2LIP_WEIGHT_HASHES[relative_path]
            for relative_path, size in WAV2LIP_WEIGHT_FILES.items()
        )
    )


def _verify_existing_checkout(git: str, repository: Path) -> None:
    origin = _capture([git, "-C", str(repository), "remote", "get-url", "origin"]).strip()
    commit = _capture([git, "-C", str(repository), "rev-parse", "HEAD"]).strip()
    if origin != WAV2LIP_REPOSITORY_URL or commit != WAV2LIP_COMMIT:
        raise RuntimeError("Existing Wav2Lip checkout does not match the pinned official source")
    diff = subprocess.run(
        [git, "-C", str(repository), "diff", "--binary", "HEAD"],
        capture_output=True,
        check=True,
    ).stdout
    diff_hash = hashlib.sha256(diff).hexdigest()
    clean_hash = hashlib.sha256(b"").hexdigest()
    if diff_hash not in {clean_hash, WAV2LIP_PATCH_DIFF_SHA256}:
        raise RuntimeError("Existing Wav2Lip checkout has unexpected tracked changes")


def install_wav2lip_runtime(plan: Wav2LipSetupPlan) -> Wav2LipRuntime:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This setup command is limited to Apple Silicon macOS")
    root = plan.runtime_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    required_free = (
        MINIMUM_REPAIR_FREE_BYTES if _runtime_materialized(root) else plan.minimum_free_bytes
    )
    available = shutil.disk_usage(root).free
    if available < required_free:
        raise RuntimeError(
            f"Wav2Lip setup requires at least {required_free} free bytes; found {available}"
        )

    git = _required_executable("git")
    uv = _required_executable("uv")
    ffmpeg = _required_executable("ffmpeg")
    repository = root / "repository"
    environment = root / ".venv"
    python = environment / "bin/python"
    if repository.exists():
        if not (repository / ".git").is_dir():
            raise RuntimeError(f"Existing repository path is not a Git checkout: {repository}")
        _verify_existing_checkout(git, repository)
    else:
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
    _run([git, "-C", str(repository), "fetch", "--depth", "1", "origin", plan.commit])
    _run([git, "-C", str(repository), "checkout", "--detach", plan.commit])
    apply_wav2lip_compatibility_patches(repository)

    _run([uv, "python", "install", plan.python_version])
    if not _python_matches(python, plan.python_version):
        clear = ["--clear"] if environment.exists() else []
        _run([uv, "venv", *clear, "--python", plan.python_version, str(environment)])
    install_env = {**os.environ, "UV_NO_CACHE": "1"}
    _run(
        [uv, "pip", "sync", "--python", str(python), str(plan.lock_file)],
        env=install_env,
    )

    download = (
        "import sys; from huggingface_hub import hf_hub_download; "
        "print(hf_hub_download(repo_id=sys.argv[1], revision=sys.argv[2], "
        "filename=sys.argv[3], local_dir=sys.argv[4]))"
    )
    downloads = (
        (
            WAV2LIP_MODEL_REPOSITORY,
            WAV2LIP_MODEL_REVISION,
            "Wav2lip/wav2lip.pth",
            repository / "checkpoints/wav2lip.pth",
        ),
        (
            S3FD_MODEL_REPOSITORY,
            S3FD_MODEL_REVISION,
            "auxiliary/s3fd-619a316812.pth",
            repository / "face_detection/detection/sfd/s3fd.pth",
        ),
    )
    for repo_id, revision, filename, destination in downloads:
        _assert_no_symlink_destination(destination, root=repository)
        if (
            destination.is_file()
            and _sha256(destination) == WAV2LIP_WEIGHT_HASHES[destination.relative_to(repository)]
        ):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        downloaded = _capture(
            [str(python), "-c", download, repo_id, revision, filename, str(root / "downloads")]
        ).strip()
        relative_path = destination.relative_to(repository)
        _install_verified_weight(
            Path(downloaded),
            destination,
            root=repository,
            expected_sha256=WAV2LIP_WEIGHT_HASHES[relative_path],
        )

    runtime = Wav2LipRuntime(repository, python)
    diagnostic = inspect_wav2lip_runtime(runtime, ffmpeg=Path(ffmpeg))
    if not diagnostic.ready:
        raise RuntimeError("Wav2Lip runtime verification failed: " + "; ".join(diagnostic.issues))
    return runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/wav2lip"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_wav2lip_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        payload["lock_file"] = str(plan.lock_file)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    runtime = install_wav2lip_runtime(plan)
    print(
        json.dumps(
            {"python": str(runtime.python), "repository": str(runtime.repository), "ready": True}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
