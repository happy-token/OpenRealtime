"""Install the pinned official LivePortrait human runtime in an isolated directory."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.liveportrait_provider import (
    HUMAN_WEIGHT_FILES,
    HUMAN_WEIGHT_HASHES,
    LIVEPORTRAIT_COMMIT,
    LIVEPORTRAIT_MODEL_REVISION,
    LIVEPORTRAIT_REPOSITORY_URL,
    LivePortraitRuntime,
    _sha256,
    inspect_liveportrait_runtime,
)

MINIMUM_FREE_BYTES = 12 * 1024**3
MINIMUM_REPAIR_FREE_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class LivePortraitSetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    model_revision: str
    python_version: str
    minimum_free_bytes: int
    expected_weight_bytes: int
    lock_file: Path
    weight_files: tuple[str, ...]


def build_liveportrait_setup_plan(runtime_root: Path) -> LivePortraitSetupPlan:
    """Return the pinned, human-only install plan without changing the machine."""

    return LivePortraitSetupPlan(
        runtime_root=runtime_root,
        repository_url=LIVEPORTRAIT_REPOSITORY_URL,
        commit=LIVEPORTRAIT_COMMIT,
        model_revision=LIVEPORTRAIT_MODEL_REVISION,
        python_version="3.10.20",
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        expected_weight_bytes=sum(HUMAN_WEIGHT_FILES.values()),
        lock_file=Path(__file__).with_name("locks") / "liveportrait-macos-arm64-py310.txt",
        weight_files=tuple(path.as_posix() for path in HUMAN_WEIGHT_FILES),
    )


def install_liveportrait_runtime(plan: LivePortraitSetupPlan) -> LivePortraitRuntime:
    """Install and verify the official runtime described by ``plan``."""

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This setup command is limited to Apple Silicon macOS")

    runtime_root = plan.runtime_root.resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    repository = runtime_root / "repository"
    environment = runtime_root / ".venv"
    python = environment / "bin/python"
    weights_root = repository / "pretrained_weights"
    runtime_is_materialized = (
        (repository / "inference.py").is_file()
        and python.is_file()
        and all(
            _verified_weight(
                weights_root / relative_path,
                root=weights_root,
                expected_size=expected_size,
                expected_sha256=HUMAN_WEIGHT_HASHES[relative_path],
            )
            for relative_path, expected_size in HUMAN_WEIGHT_FILES.items()
        )
    )
    available_bytes = shutil.disk_usage(runtime_root).free
    required_free_bytes = (
        MINIMUM_REPAIR_FREE_BYTES if runtime_is_materialized else plan.minimum_free_bytes
    )
    if available_bytes < required_free_bytes:
        raise RuntimeError(
            f"LivePortrait setup requires at least {required_free_bytes} free bytes; "
            f"found {available_bytes}"
        )

    git = _required_executable("git")
    uv = _required_executable("uv")
    ffmpeg = _required_executable("ffmpeg")
    if repository.exists():
        if not (repository / ".git").is_dir():
            raise RuntimeError(f"Existing repository path is not a Git checkout: {repository}")
        _require_clean_tracked_checkout(git, repository)
        origin = _capture([git, "-C", str(repository), "remote", "get-url", "origin"])
        if origin.strip() != plan.repository_url:
            raise RuntimeError(f"Unexpected LivePortrait origin: {origin.strip()}")
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

    _run([uv, "python", "install", plan.python_version])
    if not _python_matches(python, plan.python_version):
        clear = ["--clear"] if environment.exists() else []
        _run([uv, "venv", *clear, "--python", plan.python_version, str(environment)])

    install_environment = {**os.environ, "UV_NO_CACHE": "1"}
    _run(
        [uv, "pip", "sync", "--python", str(python), str(plan.lock_file)],
        env=install_environment,
    )

    download_program = (
        "import sys; from huggingface_hub import hf_hub_download; "
        "print(hf_hub_download(repo_id='KlingTeam/LivePortrait', "
        "filename=sys.argv[2], revision=sys.argv[1]))"
    )
    for relative_path, expected_size in HUMAN_WEIGHT_FILES.items():
        destination = weights_root / relative_path
        expected_sha256 = HUMAN_WEIGHT_HASHES[relative_path]
        if _verified_weight(
            destination,
            root=weights_root,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        ):
            continue
        downloaded = _capture(
            [
                str(python),
                "-c",
                download_program,
                plan.model_revision,
                relative_path.as_posix(),
            ]
        ).strip()
        _install_verified_weight(
            Path(downloaded),
            destination,
            root=weights_root,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    runtime = LivePortraitRuntime(repository=repository, python=python)
    diagnostic = inspect_liveportrait_runtime(runtime, ffmpeg=Path(ffmpeg))
    if not diagnostic.ready:
        raise RuntimeError(
            "LivePortrait runtime verification failed: " + "; ".join(diagnostic.issues)
        )
    return runtime


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required executable is missing: {name}")
    return executable


def _assert_no_symlink_destination(destination: Path, *, root: Path) -> None:
    absolute_root = Path(os.path.abspath(root))
    absolute_destination = Path(os.path.abspath(destination))
    try:
        relative = absolute_destination.relative_to(absolute_root)
    except ValueError as error:
        raise RuntimeError(f"Weight destination escapes runtime: {destination}") from error
    cursor = absolute_root
    if cursor.is_symlink():
        raise RuntimeError(f"Weight root must not be a symbolic link: {root}")
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise RuntimeError(f"Weight path must not contain a symbolic link: {cursor}")


def _verified_weight(
    path: Path,
    *,
    root: Path,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    _assert_no_symlink_destination(path, root=root)
    return (
        path.is_file() and path.stat().st_size == expected_size and _sha256(path) == expected_sha256
    )


def _install_verified_weight(
    downloaded: Path,
    destination: Path,
    *,
    root: Path,
    expected_size: int,
    expected_sha256: str,
) -> None:
    _assert_no_symlink_destination(destination, root=root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink_destination(destination, root=root)
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", dir=destination.parent, delete=False
    ) as temporary_handle:
        temporary = Path(temporary_handle.name)
    try:
        shutil.copyfile(downloaded, temporary)
        if temporary.stat().st_size != expected_size or _sha256(temporary) != expected_sha256:
            raise RuntimeError(f"Downloaded weight verification failed: {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _require_clean_tracked_checkout(git: str, repository: Path) -> None:
    status = _capture(
        [git, "-C", str(repository), "status", "--porcelain", "--untracked-files=all"]
    )
    if status.strip():
        raise RuntimeError(f"LivePortrait checkout has unexpected changes: {repository}")


def _capture(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, check=True, text=True).stdout


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/liveportrait"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_liveportrait_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        payload["lock_file"] = str(plan.lock_file)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    runtime = install_liveportrait_runtime(plan)
    print(
        json.dumps(
            {"python": str(runtime.python), "repository": str(runtime.repository), "ready": True},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
