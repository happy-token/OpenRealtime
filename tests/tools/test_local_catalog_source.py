import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from server.tools.local_catalog_source import LocalCatalogToolSource
from server.tools.canonical import ConfirmationRequirement, RiskLevel, ToolEffect


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        if self.path == "/mcp" and payload["method"] == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/mcp" and payload["method"] == "initialize":
            result = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "test", "version": "1"}}}
        elif self.path == "/mcp":
            result = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": payload["params"]["arguments"]["city"]}]}}
        else:
            result = {"received": payload}
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


@pytest.mark.asyncio
async def test_custom_tool_requires_operator_origin_and_role_binding(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/function"
    tool_root = tmp_path / "tools"
    role_root = tmp_path / "roles"
    tool_root.mkdir()
    role_root.mkdir()
    (tool_root / "tools.json").write_text(json.dumps([{
        "tool_id": "tool-order", "function_name": "get_order_status", "description": "Query order",
        "kind": "function", "endpoint": endpoint, "enabled": True, "public_enabled": False,
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    }]))
    (role_root / "roles.json").write_text(json.dumps([{"role_id": "role-one", "tool_ids": ["tool-order"]}, {"role_id": "role-two", "tool_ids": []}]))
    try:
        assert LocalCatalogToolSource(tool_root=tool_root, role_root=role_root).list_tools() == []
        monkeypatch.setenv("VOICEAGENT_TOOL_ALLOWED_ORIGINS", f"http://127.0.0.1:{server.server_port}")
        source = LocalCatalogToolSource(tool_root=tool_root, role_root=role_root)
        tool = source.list_tools()[0]
        with pytest.raises(ValueError, match="not bound"):
            await tool.handler({"order_id": "42"})
        assert LocalCatalogToolSource(tool_root=tool_root, role_root=role_root, public_only=True).list_tools() == []
        records = json.loads((tool_root / "tools.json").read_text())
        records[0]["public_enabled"] = True
        records[0]["risk_level"] = "high"
        records[0]["effect"] = "write_irreversible"
        (tool_root / "tools.json").write_text(json.dumps(records))
        public_source = LocalCatalogToolSource(tool_root=tool_root, role_root=role_root, public_only=True)
        graded = public_source.list_tools()[0]
        assert graded.risk is RiskLevel.HIGH
        assert graded.effects == frozenset({ToolEffect.WRITE_IRREVERSIBLE})
        assert graded.confirmation is ConfirmationRequirement.STRONG
        assert public_source.select_role("role-one") == {"get_order_status"}
        assert source.select_role("role-one") == {"get_order_status"}
        assert json.loads(await tool.handler({"order_id": "42"})) == {"received": {"order_id": "42"}}
        assert source.select_role("role-two") == set()
        with pytest.raises(ValueError, match="not bound"):
            await tool.handler({"order_id": "42"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_streamable_http_mcp_tool_call(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("VOICEAGENT_TOOL_ALLOWED_ORIGINS", origin)
    tool_root = tmp_path / "tools"
    role_root = tmp_path / "roles"
    tool_root.mkdir()
    role_root.mkdir()
    (tool_root / "tools.json").write_text(json.dumps([{
        "tool_id": "tool-weather", "function_name": "get_weather", "description": "Weather",
        "kind": "mcp", "mcp_transport": "streamable-http", "endpoint": origin + "/mcp",
        "enabled": True, "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
    }]))
    (role_root / "roles.json").write_text(json.dumps([{"role_id": "role-one", "tool_ids": ["tool-weather"]}]))
    try:
        source = LocalCatalogToolSource(tool_root=tool_root, role_root=role_root)
        source.select_role("role-one")
        result = json.loads(await source.list_tools()[0].handler({"city": "Shanghai"}))
        assert result == {"content": [{"type": "text", "text": "Shanghai"}]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
