"""Install the pinned DH_live_mini v1 preprocessing runtime for Apple Silicon."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.dh_live_v1_provider import DH_LIVE_V1_COMMIT
from scripts.prepare_dh_live_v1_avatar import (
    DINET_WEIGHT_SHA256,
    DINET_WEIGHT_SIZE,
    PATCHED_SOURCE_TREE_SHA256,
    _sha256,
    _source_tree_sha256,
    inspect_dh_live_v1_runtime,
)

DH_LIVE_REPOSITORY_URL = "https://github.com/kleinlee/DH_live.git"
DINET_WEIGHT_URL = (
    "https://drive.usercontent.google.com/download?"
    "id=188DuCWxS5CB2yQlMkNOHSkwF-0iQW7Q9&export=download&confirm=t"
)
MINIMUM_FREE_BYTES = 2 * 1024**3
COMMAND_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class DHLiveV1SetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    python_version: str
    checkpoint_size_bytes: int
    checkpoint_sha256: str
    patched_source_tree_sha256: str
    lock_file: Path


def build_dh_live_v1_setup_plan(runtime_root: Path) -> DHLiveV1SetupPlan:
    return DHLiveV1SetupPlan(
        runtime_root=runtime_root,
        repository_url=DH_LIVE_REPOSITORY_URL,
        commit=DH_LIVE_V1_COMMIT,
        python_version="3.10.20",
        checkpoint_size_bytes=DINET_WEIGHT_SIZE,
        checkpoint_sha256=DINET_WEIGHT_SHA256,
        patched_source_tree_sha256=PATCHED_SOURCE_TREE_SHA256,
        lock_file=Path(__file__).with_name("locks") / "dh-live-v1-macos-arm64-py310.txt",
    )


def _git_environment() -> dict[str, str]:
    environment = {
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    for name in ("LANG", "LC_ALL"):
        if value := os.environ.get(name):
            environment[name] = value
    return environment


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            env=environment,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Command timed out: {command[0]}") from error


def _extract_verified_snapshot(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r") as source:
        for member in source.getmembers():
            member_path = Path(member.name)
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or not (member.isdir() or member.isfile())
            ):
                raise RuntimeError(f"Unsafe path in DH_live v1 source archive: {member.name}")
        source.extractall(destination, filter="data")


def apply_dh_live_v1_patches(repository: Path) -> None:
    render_model = repository / "talkingface/render_model_mini.py"
    source = render_model.read_text(encoding="utf-8")
    replacements = {
        "torch.load(ckpt_path, map_location=device)": (
            "torch.load(ckpt_path, map_location=device, weights_only=True)"
        ),
        "random.sample(glob.glob(teeth_ref_img), 1)[0]": "sorted(glob.glob(teeth_ref_img))[0]",
    }
    for old, new in replacements.items():
        if new not in source:
            if old not in source:
                raise RuntimeError(f"DH_live v1 compatibility patch no longer applies: {old}")
            source = source.replace(old, new)
    render_model.write_text(source, encoding="utf-8")

    html = repository / "web_demo/static/MiniLive.html"
    html_source = html.read_text(encoding="utf-8")
    old_iframe = (
        '<iframe id="screen2" src="dialog.html" frameborder="0" style="display: none;"></iframe>'
    )
    safe_placeholder = '<div id="screen2" style="display: none;"></div>'
    if safe_placeholder not in html_source:
        if old_iframe not in html_source:
            raise RuntimeError("DH_live v1 iframe removal patch no longer applies")
        html.write_text(html_source.replace(old_iframe, safe_placeholder), encoding="utf-8")


def _download_checkpoint(destination: Path) -> None:
    destination.parent.mkdir(parents=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, prefix=".epoch-40.", delete=False
        ) as output:
            temporary_path = Path(output.name)
            request = urllib.request.Request(
                DINET_WEIGHT_URL,
                headers={"User-Agent": "OpenRealtime-DHLiveV1/1.0"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    if output.tell() > DINET_WEIGHT_SIZE:
                        raise RuntimeError("DH_live v1 checkpoint exceeds the pinned size")
            output.flush()
            os.fsync(output.fileno())
        if (
            temporary_path.stat().st_size != DINET_WEIGHT_SIZE
            or _sha256(temporary_path) != DINET_WEIGHT_SHA256
        ):
            raise RuntimeError("DH_live v1 checkpoint hash mismatch")
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def install_dh_live_v1_runtime(plan: DHLiveV1SetupPlan) -> Path:
    if plan != build_dh_live_v1_setup_plan(plan.runtime_root):
        raise ValueError("DH_live v1 setup plan does not match the pinned definition")
    if plan.runtime_root.is_symlink():
        raise RuntimeError("DH_live v1 runtime root cannot be a symbolic link")
    root = plan.runtime_root.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists():
        issues = inspect_dh_live_v1_runtime(root)
        if issues:
            raise RuntimeError("Existing DH_live v1 runtime is invalid: " + "; ".join(issues))
        return root
    if shutil.disk_usage(root.parent).free < MINIMUM_FREE_BYTES:
        raise RuntimeError("DH_live v1 setup requires at least 2 GiB free space")
    git = shutil.which("git")
    uv = shutil.which("uv")
    if not git or not uv:
        raise RuntimeError("git and uv are required")
    with tempfile.TemporaryDirectory(prefix=".dh-live-v1-", dir=root.parent) as staging_name:
        staging = Path(staging_name)
        clone = staging / "clone"
        archive = staging / "source.tar"
        publish = staging / "publish"
        repository = publish / "repository"
        empty_template = staging / "empty-git-template"
        empty_template.mkdir()
        git_environment = _git_environment()
        _run(
            [
                git,
                "-c",
                f"core.hooksPath={os.devnull}",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                f"--template={empty_template}",
                plan.repository_url,
                str(clone),
            ],
            environment=git_environment,
        )
        _run(
            [
                git,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(clone),
                "fetch",
                "--depth",
                "1",
                "origin",
                plan.commit,
            ],
            environment=git_environment,
        )
        _run(
            [
                git,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(clone),
                "archive",
                "--format=tar",
                f"--output={archive}",
                plan.commit,
            ],
            environment=git_environment,
        )
        _extract_verified_snapshot(archive, repository)
        apply_dh_live_v1_patches(repository)
        source_tree_hash = _source_tree_sha256(repository)
        if source_tree_hash != PATCHED_SOURCE_TREE_SHA256:
            raise RuntimeError("DH_live v1 patched source tree hash mismatch: " + source_tree_hash)
        _download_checkpoint(repository / "checkpoint/DINet_mini/epoch_40.pth")
        _run([uv, "venv", str(publish / ".venv"), "--python", plan.python_version])
        _run(
            [
                uv,
                "pip",
                "sync",
                str(plan.lock_file.resolve()),
                "--python",
                str(publish / ".venv/bin/python"),
            ]
        )
        issues = inspect_dh_live_v1_runtime(publish)
        if issues:
            raise RuntimeError("DH_live v1 runtime verification failed: " + "; ".join(issues))
        os.replace(publish, root)
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/dh_live_v1"))
    args = parser.parse_args()
    plan = build_dh_live_v1_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        payload["lock_file"] = str(plan.lock_file)
        print(__import__("json").dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    root = install_dh_live_v1_runtime(plan)
    print(__import__("json").dumps({"runtime_root": str(root), "ready": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
