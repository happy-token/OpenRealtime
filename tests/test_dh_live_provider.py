import http.client
import http.server
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

import pytest

from scripts.dh_live_provider import (
    DHLiveRuntime,
    SafeDHLiveRequestHandler,
    create_dh_live_server,
    inspect_dh_live_assets,
    validate_dh_live_serve_options,
)


def test_serve_options_resolve_pinned_static_root() -> None:
    runtime = DHLiveRuntime(Path("/models/dh_live/repository"), Path("/python"))

    static_root = validate_dh_live_serve_options(runtime, port=8890)

    assert static_root == Path("/models/dh_live/repository/web_demo/static")


def test_server_command_rejects_invalid_port_and_marketing_use() -> None:
    runtime = DHLiveRuntime(Path("repo"), Path("python"))

    with pytest.raises(ValueError, match="port"):
        validate_dh_live_serve_options(runtime, port=0)
    with pytest.raises(ValueError, match="port"):
        validate_dh_live_serve_options(runtime, port=True)
    with pytest.raises(ValueError, match="port"):
        validate_dh_live_serve_options(runtime, port=8890.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="authorization"):
        validate_dh_live_serve_options(runtime, usage_scope="commercial_marketing")


def test_safe_handler_blocks_dialog_and_adds_security_headers(tmp_path: Path) -> None:
    (tmp_path / "MiniLive.html").write_text("renderer", encoding="utf-8")
    (tmp_path / "unverified.html").write_text("unsafe", encoding="utf-8")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SafeDHLiveRequestHandler, directory=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/dialog.html")
        blocked = connection.getresponse()
        assert blocked.status == 404
        blocked.read()
        connection.request("GET", "/unverified.html")
        unverified = connection.getresponse()
        assert unverified.status == 404
        unverified.read()
        connection.request("GET", "/MiniLive.html")
        allowed = connection.getresponse()
        assert allowed.status == 200
        assert allowed.getheader("Content-Security-Policy")
        assert allowed.getheader("X-Frame-Options") == "DENY"
        allowed.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_create_server_is_loopback_only(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runtime = DHLiveRuntime(repository, Path("/python"))

    server = create_dh_live_server(
        runtime,
        port=0,
        usage_scope="research",
        allow_ephemeral=True,
    )
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_diagnose_cli_reports_missing_runtime_as_json(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/dh_live_provider.py",
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
    assert '"ready": false' in result.stdout
    assert "missing DH_live repository" in result.stdout


def test_asset_inspection_rejects_an_intermediate_directory_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    target = tmp_path / "target"
    (repository / "web_demo").mkdir(parents=True)
    target.mkdir()
    (repository / "web_demo" / "static").symlink_to(target, target_is_directory=True)

    issues = inspect_dh_live_assets(repository)

    assert any("symbolic link in browser runtime asset path" in issue for issue in issues)
