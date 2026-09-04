"""Real ACP (Agent Client Protocol) `Driver` conformer — see
docs/adr/0017-acp-driver-real-agent-backend-conformer.md.

Speaks JSON-RPC 2.0 over NDJSON on stdio to any ACP-compliant coding-agent
CLI (e.g. ``opencode acp``), the same wire protocol used by the official
``@agentclientprotocol/sdk`` (qwen-audio-agent's own dependency). One
subprocess is spawned per `AcpDriver` and reused across sessions/turns; each
`AcpAgentSession` maps to one ACP ``sessionId`` on that shared subprocess.

``session/request_permission`` requests from the agent are answered per
``permission_policy`` (fail-closed by default). No ``fs/*``/``terminal/*`` request handling is
implemented: a backend that needs those will hang the same way the live
qwen-audio-agent test did. That is a documented follow-up, not silently
patched around.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from server.agent_session.protocol import DelegationOutcome
from server.core.turn_content import TurnContent

PROTOCOL_VERSION = 1

_ACTIVE_STOP_REASONS = frozenset({"end_turn", "max_tokens", "max_turn_requests"})


class AcpError(RuntimeError):
    """Raised when the ACP subprocess reports a JSON-RPC error, exits
    unexpectedly, or sends a malformed message."""


class _Update:
    def __init__(self, text: str) -> None:
        self.text = text


class AcpTransport(Protocol):
    async def start(self) -> None: ...
    async def write_line(self, data: bytes) -> None: ...
    async def readline(self) -> bytes: ...
    async def close(self) -> None: ...


class SubprocessAcpTransport:
    """Real conformer: one child process, NDJSON on its stdin/stdout. Stderr
    is captured (not streamed) so a crash can be reported with useful
    context via `AcpError`.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._env = {**os.environ, **env} if env is not None else None
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )

    async def write_line(self, data: bytes) -> None:
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(data + b"\n")
        await self._process.stdin.drain()

    async def readline(self) -> bytes:
        assert self._process is not None and self._process.stdout is not None
        return await self._process.stdout.readline()

    async def stderr_text(self) -> str:
        if self._process is None or self._process.stderr is None:
            return ""
        remaining = await self._process.stderr.read()
        return remaining.decode(errors="replace")

    async def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.returncode is None:
            self._process.terminate()
        await self._process.wait()


def _select_permission_option(options: list[dict[str, Any]], *, approve: bool) -> str | None:
    if not options:
        return None
    wanted_prefix = "allow" if approve else "reject"
    for option in options:
        if str(option.get("kind", "")).startswith(wanted_prefix):
            return option.get("optionId")
    return options[0].get("optionId")


class _AcpJsonRpcClient:
    """Owns one transport and one background read loop; correlates
    JSON-RPC requests by id and dispatches notifications/peer requests.
    """

    def __init__(
        self,
        transport: AcpTransport,
        *,
        on_notification: Callable[[str, dict[str, Any]], None],
        on_peer_request: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._transport = transport
        self._on_notification = on_notification
        self._on_peer_request = on_peer_request
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_loop_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._read_loop_task = asyncio.ensure_future(self._read_loop())

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = next(self._ids)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        await self._transport.write_line(json.dumps(message).encode())

    async def _read_loop(self) -> None:
        while True:
            try:
                raw = await self._transport.readline()
            except OSError as error:
                self._fail_all(AcpError(f"ACP transport read failed: {error}"))
                return
            if not raw:
                self._fail_all(AcpError(await self._crash_reason()))
                return
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as error:
                self._fail_all(AcpError(f"Malformed ACP message: {raw!r} ({error})"))
                return
            try:
                self._dispatch(message)
            except AcpError as error:
                self._fail_all(error)
                return

    async def _crash_reason(self) -> str:
        stderr_text = ""
        get_stderr = getattr(self._transport, "stderr_text", None)
        if get_stderr is not None:
            stderr_text = await get_stderr()
        suffix = f" stderr: {stderr_text}" if stderr_text else ""
        return f"ACP agent process exited unexpectedly.{suffix}"

    def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        message_id = message.get("id")
        if method is not None and message_id is None:
            self._on_notification(method, message.get("params") or {})
            return
        if method is not None and message_id is not None:
            asyncio.ensure_future(self._respond_to_peer_request(message_id, method, message.get("params") or {}))
            return
        if message_id is not None:
            self._resolve(message_id, message)
            return
        raise AcpError(f"Malformed ACP message: {message!r}")

    async def _respond_to_peer_request(self, request_id: Any, method: str, params: dict[str, Any]) -> None:
        try:
            result = self._on_peer_request(method, params)
        except AcpError as error:
            await self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": str(error)}})
            return
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _resolve(self, request_id: Any, message: dict[str, Any]) -> None:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(AcpError(str(message["error"])))
        else:
            future.set_result(message.get("result") or {})

    def _fail_all(self, error: AcpError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

    async def close(self) -> None:
        if self._read_loop_task is not None:
            self._read_loop_task.cancel()
            await asyncio.gather(self._read_loop_task, return_exceptions=True)
            self._read_loop_task = None
        await self._transport.close()


class AcpDriver:
    """`Driver` conformer: spawns one ACP-stdio agent subprocess, shared
    across every session it creates.
    """

    def __init__(
        self,
        command: Sequence[str] = ("opencode", "acp"),
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        permission_policy: Callable[[dict[str, Any]], bool] = lambda _: False,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._env = env
        self._permission_policy = permission_policy
        self._client: _AcpJsonRpcClient | None = None
        self._start_lock = asyncio.Lock()
        self._sessions_by_id: dict[str, AcpAgentSession] = {}

    def create_session(self) -> AcpAgentSession:
        return AcpAgentSession(self)

    async def close(self) -> None:
        """Close the shared ACP subprocess and forget process-local sessions."""
        async with self._start_lock:
            if self._client is not None:
                await self._client.close()
                self._client = None
            self._sessions_by_id.clear()

    async def _ensure_started(self) -> _AcpJsonRpcClient:
        async with self._start_lock:
            if self._client is None:
                transport = SubprocessAcpTransport(self._command, cwd=self._cwd, env=self._env)
                await transport.start()
                client = _AcpJsonRpcClient(
                    transport,
                    on_notification=self._handle_notification,
                    on_peer_request=self._handle_peer_request,
                )
                client.start()
                await client.request(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "clientCapabilities": {},
                        "clientInfo": {"name": "openrealtime", "version": "0.1.0"},
                    },
                )
                self._client = client
            return self._client

    async def _new_acp_session(self, client: _AcpJsonRpcClient) -> str:
        response = await client.request("session/new", {"cwd": self._cwd or ".", "mcpServers": []})
        return response["sessionId"]

    def _register(self, session_id: str, session: AcpAgentSession) -> None:
        self._sessions_by_id[session_id] = session

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update":
            return
        session = self._sessions_by_id.get(params.get("sessionId"))
        if session is None:
            return
        update = params.get("update") or {}
        if update.get("sessionUpdate") == "agent_message_chunk":
            text = (update.get("content") or {}).get("text")
            if text:
                session._append_text(text)

    def _handle_peer_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method != "session/request_permission":
            raise AcpError(f"Unhandled ACP peer request: {method}")
        approved = self._permission_policy(params)
        option_id = _select_permission_option(params.get("options") or [], approve=approved)
        return {"outcome": {"outcome": "selected", "optionId": option_id}}


class AcpAgentSession:
    """`AgentSession` conformer bound to one ACP session on a shared
    `AcpDriver` subprocess.
    """

    def __init__(self, driver: AcpDriver) -> None:
        self._driver = driver
        self._session_id: str | None = None
        self._latest_text: str | None = None
        self._done = asyncio.Event()
        self._outcome: DelegationOutcome | None = None

    async def send_turn(self, content: TurnContent) -> None:
        asyncio.ensure_future(self._run_prompt(content.text))

    async def _run_prompt(self, text: str) -> None:
        try:
            client = await self._driver._ensure_started()
            if self._session_id is None:
                self._session_id = await self._driver._new_acp_session(client)
                self._driver._register(self._session_id, self)
            response = await client.request(
                "session/prompt",
                {"sessionId": self._session_id, "prompt": [{"type": "text", "text": text}]},
            )
            stop_reason = response.get("stopReason")
            if stop_reason in _ACTIVE_STOP_REASONS:
                self._outcome = DelegationOutcome(ok=True, text=self._latest_text)
            else:
                self._outcome = DelegationOutcome(
                    ok=False, error=f"ACP turn ended with stopReason={stop_reason!r}"
                )
        except (AcpError, OSError) as error:
            self._outcome = DelegationOutcome(ok=False, error=str(error))
        finally:
            self._done.set()

    async def latest_update(self) -> _Update | None:
        if self._latest_text is None:
            return None
        return _Update(self._latest_text)

    async def cancel(self) -> None:
        client = self._driver._client
        if client is not None and self._session_id is not None:
            await client.notify("session/cancel", {"sessionId": self._session_id})

    async def result(self) -> DelegationOutcome:
        await self._done.wait()
        assert self._outcome is not None
        return self._outcome

    def _append_text(self, chunk: str) -> None:
        self._latest_text = (self._latest_text or "") + chunk
