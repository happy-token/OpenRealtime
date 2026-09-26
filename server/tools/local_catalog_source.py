"""Role-bound HTTP and Streamable HTTP MCP tools for the local tool runtime.

Endpoint origins are set by the operator, never by a model response. The catalog is
read once per session, while role binding is checked when the client selects a role.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from server.tools.canonical import (
    CanonicalTool, ConfirmationRequirement, IdempotencyClass, LatencyClass,
    RiskLevel, ToolEffect,
)
from server.brain.role_model import role_tool_ids

_MAX_RESPONSE = 16_384
_MAX_ARGUMENTS = 8_192


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError("Tool endpoint redirects are not allowed")


def _allowed_origin(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return False
    allowed = {value.strip().rstrip("/") for value in os.environ.get("VOICEAGENT_TOOL_ALLOWED_ORIGINS", "").split(",") if value.strip()}
    return f"{parsed.scheme}://{parsed.netloc}" in allowed


def _request(url: str, payload: dict[str, Any] | None, *, headers: dict[str, str] | None = None) -> tuple[dict[str, str], Any]:
    if not _allowed_origin(url):
        raise ValueError("Tool endpoint origin is not operator-approved")
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=encoded, headers={"Accept": "application/json, text/event-stream", **(headers or {}), **({"Content-Type": "application/json"} if encoded is not None else {})}, method="POST" if encoded is not None else "GET")
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=5) as response:
            if response.status >= 300:
                raise ValueError("Tool endpoint returned an unsuccessful status")
            body = response.read(_MAX_RESPONSE + 1)
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        raise ValueError(f"Tool endpoint returned HTTP {error.code}") from None
    if len(body) > _MAX_RESPONSE:
        raise ValueError("Tool response exceeds 16KB")
    if response_headers.get("Content-Type", "").startswith("text/event-stream"):
        messages = [line[5:].lstrip() for line in body.decode("utf-8").splitlines() if line.startswith("data:")]
        if not messages:
            raise ValueError("MCP response contained no data")
        return response_headers, json.loads(messages[-1])
    return response_headers, json.loads(body) if body else None


def _execute_http(record: dict[str, Any], arguments: dict[str, Any]) -> str:
    endpoint = record["endpoint"]
    if record["kind"] == "api" and record.get("method") == "GET":
        parsed = urlsplit(endpoint)
        if parsed.query:
            raise ValueError("GET tool endpoint must not contain a query")
        query = urlencode(arguments, doseq=True)
        _, result = _request(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, "")), None)
    else:
        _, result = _request(endpoint, arguments)
    return json.dumps(result, ensure_ascii=False)[:_MAX_RESPONSE]


def _execute_mcp(record: dict[str, Any], arguments: dict[str, Any]) -> str:
    endpoint = record["endpoint"]
    headers, initialization = _request(endpoint, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "OpenRealtime", "version": "0.3.0"}}}, headers={"MCP-Protocol-Version": "2025-03-26"})
    if not isinstance(initialization, dict) or "result" not in initialization:
        raise ValueError("MCP initialization failed")
    session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    session_headers = {"MCP-Protocol-Version": "2025-03-26", **({"Mcp-Session-Id": session_id} if session_id else {})}
    _request(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session_headers)
    _, result = _request(endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": record["function_name"], "arguments": arguments}}, headers=session_headers)
    if not isinstance(result, dict) or "result" not in result:
        raise ValueError("MCP tool call failed")
    return json.dumps(result["result"], ensure_ascii=False)[:_MAX_RESPONSE]


class LocalCatalogToolSource:
    def __init__(self, *, tool_root: Path | None = None, role_root: Path | None = None, public_only: bool = False,
                 user_id: str = "") -> None:
        self._tool_root = tool_root or Path(os.environ.get("TOOL_CATALOG_DIR") or ".openrealtime/tool-catalog")
        self._role_root = role_root or Path(os.environ.get("ROLE_CATALOG_DIR") or ".openrealtime/role-catalog")
        self._user_id = user_id
        self._records: dict[str, dict[str, Any]] = {}
        self._allowed_names: set[str] = set()
        try:
            records = json.loads((self._tool_root / "tools.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            records = []
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict) or not record.get("enabled") or record.get("kind") not in {"function", "api", "mcp"}:
                    continue
                if public_only and record.get("public_enabled") is not True:
                    continue
                name, endpoint, schema = record.get("function_name"), record.get("endpoint"), record.get("input_schema")
                if not isinstance(name, str) or not isinstance(endpoint, str) or not isinstance(schema, dict) or not _allowed_origin(endpoint):
                    continue
                if record.get("kind") == "mcp" and record.get("mcp_transport") != "streamable-http":
                    continue
                if name not in {"get_current_datetime", "search_web", "search_knowledge_base"} and name not in self._records:
                    self._records[name] = record

    def select_role(self, role_id: str | None) -> set[str]:
        self._allowed_names.clear()
        ids = role_tool_ids(self._user_id, role_id, shared_root=self._role_root)
        self._allowed_names.update(name for name, record in self._records.items() if record.get("tool_id") in ids)
        return set(self._allowed_names)

    def list_tools(self) -> list[CanonicalTool]:
        tools = []
        for name, record in self._records.items():
            async def handler(arguments: dict[str, Any], *, tool_name: str = name) -> str:
                if tool_name not in self._allowed_names:
                    raise ValueError("Tool is not bound to the selected role")
                encoded = json.dumps(arguments, ensure_ascii=False)
                if len(encoded.encode("utf-8")) > _MAX_ARGUMENTS:
                    raise ValueError("Tool arguments exceed 8KB")
                selected = self._records[tool_name]
                implementation = _execute_mcp if selected["kind"] == "mcp" else _execute_http
                return await asyncio.to_thread(implementation, selected, arguments)
            risk = RiskLevel(record.get("risk_level")) if record.get("risk_level") in RiskLevel._value2member_map_ else RiskLevel.MEDIUM
            effect = ToolEffect(record.get("effect")) if record.get("effect") in ToolEffect._value2member_map_ else ToolEffect.READ_SENSITIVE
            confirmation = (ConfirmationRequirement.FORBIDDEN if risk is RiskLevel.CRITICAL
                            else ConfirmationRequirement.STRONG if risk is RiskLevel.HIGH or effect in {ToolEffect.WRITE_IRREVERSIBLE, ToolEffect.SPEND_OR_TRANSFER}
                            else ConfirmationRequirement.POLICY)
            tools.append(CanonicalTool(name=name, description=str(record.get("description", ""))[:400], parameters=record["input_schema"], handler=handler, effects=frozenset({effect}), risk=risk, idempotency=IdempotencyClass.UNKNOWN, latency=LatencyClass.VARIABLE, confirmation=confirmation, default_timeout_ms=7000))
        return tools
