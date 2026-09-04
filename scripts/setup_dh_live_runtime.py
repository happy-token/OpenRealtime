"""Install the pinned DH_live_mini browser runtime without Python model dependencies."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.dh_live_provider import (
    ALLOWED_USAGE_SCOPES,
    DH_LIVE_COMMIT,
    DH_LIVE_REPOSITORY_URL,
    RUNTIME_MANIFEST_NAME,
    RUNTIME_MANIFEST_SCHEMA,
    DHLiveRuntime,
    inspect_dh_live_assets,
    inspect_dh_live_runtime,
)

MINIMUM_FREE_BYTES = 256 * 1024**2
GIT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class DHLiveSetupPlan:
    runtime_root: Path
    repository_url: str
    commit: str
    minimum_free_bytes: int
    runtime: str
    license_status: str
    allowed_usage_scopes: tuple[str, ...]


def build_dh_live_setup_plan(runtime_root: Path) -> DHLiveSetupPlan:
    return DHLiveSetupPlan(
        runtime_root=runtime_root,
        repository_url=DH_LIVE_REPOSITORY_URL,
        commit=DH_LIVE_COMMIT,
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        runtime="browser-wasm-webgl",
        license_status="README claims MIT; root LICENSE absent; avatar authorization required",
        allowed_usage_scopes=tuple(sorted(ALLOWED_USAGE_SCOPES)),
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


def _run(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            env=_git_environment(),
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("DH_live source download timed out") from error


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required executable is missing: {name}")
    return executable


def _validate_plan(plan: DHLiveSetupPlan) -> None:
    expected = build_dh_live_setup_plan(plan.runtime_root)
    if plan != expected:
        raise ValueError("DH_live setup plan does not match the pinned runtime definition")


def _write_runtime_manifest(root: Path) -> None:
    payload = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "repository_url": DH_LIVE_REPOSITORY_URL,
        "commit": DH_LIVE_COMMIT,
    }
    target = root / RUNTIME_MANIFEST_NAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=f".{RUNTIME_MANIFEST_NAME}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
                raise RuntimeError(f"Unsafe path in DH_live source archive: {member.name}")
        source.extractall(destination, filter="data")


def install_dh_live_runtime(plan: DHLiveSetupPlan) -> DHLiveRuntime:
    _validate_plan(plan)
    if plan.runtime_root.is_symlink():
        raise RuntimeError("DH_live runtime root cannot be a symbolic link")
    root = plan.runtime_root.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root.parent).free < plan.minimum_free_bytes:
        raise RuntimeError(f"DH_live setup requires at least {plan.minimum_free_bytes} free bytes")
    repository = root / "repository"
    runtime = DHLiveRuntime(repository, Path(sys.executable).resolve())
    if root.exists():
        asset_issues = inspect_dh_live_assets(repository)
        if asset_issues:
            raise RuntimeError(
                "Existing DH_live runtime is invalid; move it aside before reinstalling: "
                + "; ".join(asset_issues)
            )
        _write_runtime_manifest(root)
        diagnostic = inspect_dh_live_runtime(runtime)
        if not diagnostic.ready:
            raise RuntimeError("DH_live verification failed: " + "; ".join(diagnostic.issues))
        return runtime

    git = _required_executable("git")
    with tempfile.TemporaryDirectory(prefix=".dh-live-", dir=root.parent) as staging_name:
        staging = Path(staging_name)
        source = staging / "source"
        archive = staging / "snapshot.tar"
        publish = staging / "publish"
        empty_template = staging / "empty-git-template"
        empty_template.mkdir()
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
                str(source),
            ]
        )
        _run(
            [
                git,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(source),
                "fetch",
                "--depth",
                "1",
                "origin",
                plan.commit,
            ]
        )
        _run(
            [
                git,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(source),
                "archive",
                "--format=tar",
                f"--output={archive}",
                plan.commit,
                "web_demo/static",
            ]
        )
        publish_repository = publish / "repository"
        _extract_verified_snapshot(archive, publish_repository)
        asset_issues = inspect_dh_live_assets(publish_repository)
        if asset_issues:
            raise RuntimeError("DH_live asset verification failed: " + "; ".join(asset_issues))
        _write_runtime_manifest(publish)
        os.replace(publish, root)
    runtime = DHLiveRuntime(root / "repository", Path(sys.executable).resolve())
    return runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--runtime-root", type=Path, default=Path("models/dh_live"))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_dh_live_setup_plan(args.runtime_root)
    if args.command == "plan":
        payload = asdict(plan)
        payload["runtime_root"] = str(plan.runtime_root)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    runtime = install_dh_live_runtime(plan)
    print(
        json.dumps(
            {"repository": str(runtime.repository), "python": str(runtime.python), "ready": True},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
