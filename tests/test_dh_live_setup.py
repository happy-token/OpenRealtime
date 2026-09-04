from pathlib import Path

import pytest

from scripts.setup_dh_live_runtime import (
    DHLiveSetupPlan,
    _write_runtime_manifest,
    build_dh_live_setup_plan,
    install_dh_live_runtime,
)


def test_setup_plan_pins_browser_runtime_and_restricts_usage() -> None:
    plan = build_dh_live_setup_plan(Path("models/dh_live"))

    assert plan.repository_url == "https://github.com/kleinlee/DH_live.git"
    assert plan.commit == "4467e97cd97194c2c54762043cf121c6d313db12"
    assert plan.minimum_free_bytes == 256 * 1024**2
    assert plan.runtime == "browser-wasm-webgl"
    assert plan.allowed_usage_scopes == ("internal_evaluation", "research")
    assert "root LICENSE absent" in plan.license_status


def test_installer_rejects_a_modified_security_plan_before_git(tmp_path: Path) -> None:
    pinned = build_dh_live_setup_plan(tmp_path / "runtime")
    modified = DHLiveSetupPlan(
        runtime_root=pinned.runtime_root,
        repository_url="https://example.invalid/attacker.git",
        commit=pinned.commit,
        minimum_free_bytes=pinned.minimum_free_bytes,
        runtime=pinned.runtime,
        license_status=pinned.license_status,
        allowed_usage_scopes=pinned.allowed_usage_scopes,
    )

    with pytest.raises(ValueError, match="pinned runtime"):
        install_dh_live_runtime(modified)


def test_installer_rejects_a_symbolic_link_runtime_root(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(destination, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symbolic link"):
        install_dh_live_runtime(build_dh_live_setup_plan(runtime))


def test_manifest_write_does_not_follow_a_precreated_temporary_symlink(
    tmp_path: Path,
) -> None:
    canary = tmp_path / "canary"
    canary.write_text("do not overwrite", encoding="utf-8")
    legacy_temporary = tmp_path / ".runtime-manifest.json.tmp"
    legacy_temporary.symlink_to(canary)

    _write_runtime_manifest(tmp_path)

    assert canary.read_text(encoding="utf-8") == "do not overwrite"
    assert legacy_temporary.is_symlink()
    assert (tmp_path / "runtime-manifest.json").is_file()
