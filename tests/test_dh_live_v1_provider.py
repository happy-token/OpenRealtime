import http.client
import http.server
import json
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

import pytest

from scripts import dh_live_v1_provider
from scripts.dh_live_v1_provider import (
    SafeDHLiveV1RequestHandler,
    create_dh_live_v1_server,
    inspect_dh_live_v1_bundle,
)


def test_diagnose_cli_reports_missing_bundle_as_json(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/dh_live_v1_provider.py",
            "diagnose",
            "--bundle",
            str(tmp_path / "missing"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert '"ready": false' in result.stdout
    assert "invalid bundle" in result.stdout


def test_safe_handler_blocks_unverified_paths_and_adds_headers(tmp_path: Path) -> None:
    (tmp_path / "MiniLive.html").write_text("renderer", encoding="utf-8")
    (tmp_path / "dialog.html").write_text("unsafe", encoding="utf-8")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SafeDHLiveV1RequestHandler, directory=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/dialog.html")
        blocked = connection.getresponse()
        assert blocked.status == 404
        blocked.read()
        connection.request("GET", "/MiniLive.html")
        allowed = connection.getresponse()
        assert allowed.status == 200
        assert allowed.getheader("Content-Security-Policy")
        assert allowed.getheader("X-Frame-Options") == "DENY"
        allowed.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("port", [0, True, 8892.0, 65536])
def test_create_server_rejects_invalid_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: object
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        dh_live_v1_provider,
        "inspect_dh_live_v1_bundle",
        lambda _: dh_live_v1_provider.DHLiveV1Diagnostic(True, "sample", 25, "720x1280", False, ()),
    )

    with pytest.raises(ValueError, match="port"):
        create_dh_live_v1_server(bundle, port=port)  # type: ignore[arg-type]


def test_create_server_rejects_marketing_scope_before_inspection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="authorization"):
        create_dh_live_v1_server(
            tmp_path / "missing", port=8892, usage_scope="commercial_marketing"
        )


def test_bundle_inspection_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    diagnostic = inspect_dh_live_v1_bundle(alias)

    assert diagnostic.ready is False
    assert "invalid bundle" in diagnostic.issues


def test_bundle_manifest_keeps_internal_scope_and_safe_avatar_id(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "runtime_commit": dh_live_v1_provider.DH_LIVE_V1_COMMIT,
        "avatar_id": "../escape",
        "authorized": True,
        "usage_scope": "commercial_marketing",
        "files": {},
    }
    (tmp_path / "avatar-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    diagnostic = inspect_dh_live_v1_bundle(tmp_path)

    assert "invalid avatar id" in diagnostic.issues
    assert "avatar manifest authorization must remain false" in diagnostic.issues
    assert "avatar manifest usage scope is unsupported" in diagnostic.issues
    assert "avatar manifest source video provenance is invalid" in diagnostic.issues
