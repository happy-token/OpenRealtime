"""Control-plane HTTP server: `/healthz`, `/sessions`, `/sessions/{id}/close`.

Binds to 127.0.0.1 only, no authentication (ADR-0027) — a deployer's own
network boundary is the right place to add auth if this is ever exposed
beyond localhost. Runs on a background thread via `ThreadingHTTPServer`,
the same stdlib tool `demos/voice_web_server.py` already uses for
static files, so no new dependency is introduced. HTTP handlers run off
the asyncio event loop thread; `registry` calls are bridged back onto it
with `run_coroutine_threadsafe`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from server.avatar_assets.http_api import AvatarAssetHttpResponse
from server.endpoint_session.registry import EndpointSessionRegistry
from server.observability.telemetry import DiagnosticsQuery, DiagnosticsWindow

logger = logging.getLogger(__name__)

_SESSION_CLOSE_PATH = re.compile(r"^/sessions/(?P<session_id>[^/]+)/close$")
_OBSERVABILITY_SESSION_PATH = re.compile(
    r"^/observability/sessions/(?P<session_id>[^/]+)$"
)
_RPC_TIMEOUT_S = 5.0
_VOICE_PREVIEW_TIMEOUT_S = 60.0
_MAX_DELETE_BODY_BYTES = 16_384
_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
VoicePreviewer = Callable[[str, str, int, str], Awaitable[tuple[bytes, str]]]
SessionConversationReader = Callable[[str], Awaitable[list[dict]]]
SessionHistoryDeleter = Callable[[list[str]], Awaitable[dict[str, int]]]
AvatarAssetHandler = Callable[
    [str, str, str, dict[str, str], bytes],
    Awaitable[AvatarAssetHttpResponse],
]
_MAX_AVATAR_ASSET_BODY_BYTES = 51 * 1024 * 1024
_AVATAR_ASSET_TIMEOUT_S = 900.0
_AVATAR_CANCEL_GRACE_S = 1.0


@dataclass(slots=True)
class _TrackedAvatarRequest:
    future: Future[AvatarAssetHttpResponse] | None = None
    started: bool = False


class _AvatarRequestTracker:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._accepting = True
        self._requests: dict[object, _TrackedAvatarRequest] = {}
        self._lock = threading.Lock()
        self._changed = asyncio.Event()

    def submit(
        self,
        factory: Callable[[], Awaitable[AvatarAssetHttpResponse]],
    ) -> Future[AvatarAssetHttpResponse] | None:
        token = object()
        entry = _TrackedAvatarRequest()

        async def run() -> AvatarAssetHttpResponse:
            with self._lock:
                current = self._requests.get(token)
                if current is not None:
                    current.started = True
            try:
                return await factory()
            finally:
                self._complete(token)

        with self._lock:
            if not self._accepting:
                return None
            self._requests[token] = entry
            future = asyncio.run_coroutine_threadsafe(run(), self._loop)
            entry.future = future
        future.add_done_callback(lambda _: self._discard_if_never_started(token))
        return future

    def stop_accepting(self) -> None:
        with self._lock:
            self._accepting = False

    async def drain(self, *, deadline_s: float) -> int:
        if deadline_s < 0:
            raise ValueError("avatar request drain deadline must be non-negative")
        self.stop_accepting()
        deadline = self._loop.time() + deadline_s
        while True:
            self._changed.clear()
            if self._request_count() == 0:
                return 0
            remaining = deadline - self._loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=remaining)
            except TimeoutError:
                break

        for future in self._snapshot_futures():
            future.cancel()
        cancel_deadline = self._loop.time() + _AVATAR_CANCEL_GRACE_S
        while True:
            self._changed.clear()
            count = self._request_count()
            if count == 0:
                return 0
            remaining = cancel_deadline - self._loop.time()
            if remaining <= 0:
                return count
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=remaining)
            except TimeoutError:
                return self._request_count()

    def _snapshot_futures(self) -> tuple[Future[AvatarAssetHttpResponse], ...]:
        with self._lock:
            return tuple(
                request.future
                for request in self._requests.values()
                if request.future is not None
            )

    def _request_count(self) -> int:
        with self._lock:
            return len(self._requests)

    def _complete(self, token: object) -> None:
        with self._lock:
            self._requests.pop(token, None)
        self._loop.call_soon_threadsafe(self._changed.set)

    def _discard_if_never_started(self, token: object) -> None:
        with self._lock:
            entry = self._requests.get(token)
            if entry is None or entry.started:
                return
            self._requests.pop(token, None)
        self._loop.call_soon_threadsafe(self._changed.set)


class ControlPlaneServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        *,
        avatar_requests: _AvatarRequestTracker,
    ) -> None:
        self._avatar_requests = avatar_requests
        super().__init__(server_address, request_handler)

    def stop_accepting_avatar_requests(self) -> None:
        self._avatar_requests.stop_accepting()

    async def drain_avatar_requests(self, *, deadline_s: float) -> int:
        return await self._avatar_requests.drain(deadline_s=deadline_s)


def _build_handler(
    registry: EndpointSessionRegistry,
    loop: asyncio.AbstractEventLoop,
    avatar_requests: _AvatarRequestTracker,
    diagnostics: DiagnosticsQuery | None = None,
    voice_previewer: VoicePreviewer | None = None,
    session_conversation_reader: SessionConversationReader | None = None,
    session_history_deleter: SessionHistoryDeleter | None = None,
    avatar_asset_handler: AvatarAssetHandler | None = None,
) -> type[BaseHTTPRequestHandler]:
    class ControlPlaneHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            logger.debug("control-plane: " + format, *args)

        def _write_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_avatar_response(self, response: AvatarAssetHttpResponse) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for name, value in (response.headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

        def _avatar_asset_request(self, method: str) -> None:
            if avatar_asset_handler is None:
                self._write_json(503, {"error": "avatar asset service is not configured"})
                return
            if not _is_loopback_host(self.headers.get("Host", "")):
                self._write_json(
                    403,
                    {"error": "avatar asset request is not from loopback"},
                )
                return
            origin = self.headers.get("Origin")
            if origin is not None and not _is_loopback_origin(origin):
                self._write_json(
                    403,
                    {"error": "avatar asset request is not from loopback"},
                )
                return
            parsed = urlsplit(self.path)
            body = b""
            if method == "POST":
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._write_json(400, {"error": "invalid content length"})
                    return
                if not 1 <= content_length <= _MAX_AVATAR_ASSET_BODY_BYTES:
                    self._write_json(413, {"error": "invalid avatar asset body size"})
                    return
                body = self.rfile.read(content_length)
            future = avatar_requests.submit(
                lambda: avatar_asset_handler(
                    method,
                    parsed.path,
                    parsed.query,
                    {name.lower(): value for name, value in self.headers.items()},
                    body,
                )
            )
            if future is None:
                self._write_json(503, {"error": "avatar asset service is shutting down"})
                return
            try:
                response = future.result(timeout=_AVATAR_ASSET_TIMEOUT_S)
            except FutureTimeoutError:
                future.cancel()
                raise
            self._write_avatar_response(response)

        def do_GET(self) -> None:
            try:
                self._do_get()
            except FutureTimeoutError:
                logger.warning("control-plane request timed out: path=%s", self.path)
                self._write_json(504, {"error": "control-plane request timed out"})
            except Exception as error:  # noqa: BLE001 - HTTP error boundary
                logger.error(
                    "control-plane request failed: path=%s error_type=%s",
                    self.path,
                    type(error).__name__,
                )
                self._write_json(500, {"error": "control-plane request failed"})

        def _do_get(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path.startswith("/avatar-assets/"):
                self._avatar_asset_request("GET")
                return
            if parsed.path == "/healthz":
                self._write_json(200, {"status": "ok"})
                return
            if parsed.path == "/sessions":
                future = asyncio.run_coroutine_threadsafe(
                    _list_sessions(registry), loop
                )
                self._write_json(200, future.result(timeout=_RPC_TIMEOUT_S))
                return
            if parsed.path == "/tts/preview":
                if voice_previewer is None:
                    self._write_json(404, {"error": "voice preview is not configured"})
                    return
                parameters = parse_qs(parsed.query)
                provider = parameters.get("provider", ["doubao"])[0].strip()
                voice = parameters.get("voice", [""])[0].strip()
                try:
                    speech_rate = int(parameters.get("speech_rate", ["0"])[0])
                except ValueError:
                    self._write_json(400, {"error": "speech_rate must be an integer"})
                    return
                dialect = parameters.get("dialect", [""])[0].strip()
                if dialect not in (
                    "", "cantonese", "dongbei", "henan", "hunan", "shaanxi",
                    "shandong", "sichuan", "anhui",
                ):
                    self._write_json(400, {"error": "unsupported dialect"})
                    return
                if provider not in ("bailian", "doubao") or not voice or not -50 <= speech_rate <= 100:
                    self._write_json(400, {"error": "invalid voice preview parameters"})
                    return
                future = asyncio.run_coroutine_threadsafe(
                    voice_previewer(provider, voice, speech_rate, dialect), loop
                )
                try:
                    audio, content_type = future.result(timeout=_VOICE_PREVIEW_TIMEOUT_S)
                except ValueError:
                    self._write_json(400, {"error": "unsupported voice"})
                    return
                except RuntimeError:
                    self._write_json(503, {"error": "voice preview is unavailable"})
                    return
                self._write_bytes(200, audio, content_type)
                return
            if parsed.path == "/observability/overview":
                if diagnostics is None:
                    self._write_json(404, {"error": "diagnostics are not configured"})
                    return
                try:
                    window = _diagnostics_window(parsed.query)
                except ValueError as error:
                    self._write_json(400, {"error": str(error)})
                    return
                future = asyncio.run_coroutine_threadsafe(
                    diagnostics.overview(window), loop
                )
                overview = future.result(timeout=_RPC_TIMEOUT_S)
                self._write_json(200, overview.to_dict())
                return
            if parsed.path == "/observability/sessions":
                if diagnostics is None:
                    self._write_json(404, {"error": "diagnostics are not configured"})
                    return
                try:
                    window = _diagnostics_window(parsed.query)
                    limit = _session_limit(parsed.query)
                except ValueError as error:
                    self._write_json(400, {"error": str(error)})
                    return
                future = asyncio.run_coroutine_threadsafe(
                    diagnostics.list_sessions(window, limit=limit), loop
                )
                sessions = future.result(timeout=_RPC_TIMEOUT_S)
                self._write_json(200, [session.to_dict() for session in sessions])
                return
            match = _OBSERVABILITY_SESSION_PATH.match(parsed.path)
            if match is not None:
                if diagnostics is None:
                    self._write_json(404, {"error": "diagnostics are not configured"})
                    return
                session_id = unquote(match.group("session_id"))
                future = asyncio.run_coroutine_threadsafe(
                    diagnostics.session_detail(session_id), loop
                )
                detail = future.result(timeout=_RPC_TIMEOUT_S)
                if detail is None:
                    self._write_json(404, {"error": f"no telemetry for session: {session_id}"})
                    return
                self._write_json(200, detail.to_dict())
                return
            if parsed.path.startswith("/observability/sessions/") and parsed.path.endswith("/conversation"):
                if session_conversation_reader is None:
                    self._write_json(404, {"error": "conversation replay is not configured"})
                    return
                encoded_session_id = parsed.path.removeprefix(
                    "/observability/sessions/"
                ).removesuffix("/conversation")
                session_id = unquote(encoded_session_id.strip("/"))
                if not session_id or len(session_id) > 128:
                    self._write_json(400, {"error": "invalid session id"})
                    return
                future = asyncio.run_coroutine_threadsafe(
                    session_conversation_reader(session_id), loop
                )
                self._write_json(200, future.result(timeout=_RPC_TIMEOUT_S))
                return
            self._write_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                self._do_post()
            except FutureTimeoutError:
                logger.warning("control-plane request timed out: path=%s", self.path)
                self._write_json(504, {"error": "control-plane request timed out"})
            except Exception as error:  # noqa: BLE001 - HTTP error boundary
                logger.error(
                    "control-plane request failed: path=%s error_type=%s",
                    self.path,
                    type(error).__name__,
                )
                self._write_json(500, {"error": "control-plane request failed"})

        def do_DELETE(self) -> None:
            try:
                self._do_delete()
            except FutureTimeoutError:
                logger.warning("control-plane request timed out: path=%s", self.path)
                self._write_json(504, {"error": "control-plane request timed out"})
            except Exception as error:  # noqa: BLE001 - HTTP error boundary
                logger.error(
                    "control-plane request failed: path=%s error_type=%s",
                    self.path,
                    type(error).__name__,
                )
                self._write_json(500, {"error": "control-plane request failed"})

        def _do_post(self) -> None:
            if urlsplit(self.path).path.startswith("/avatar-assets/"):
                self._avatar_asset_request("POST")
                return
            match = _SESSION_CLOSE_PATH.match(self.path)
            if match is None:
                self._write_json(404, {"error": "not found"})
                return
            session_id = match.group("session_id")
            future = asyncio.run_coroutine_threadsafe(
                registry.close_session(session_id), loop
            )
            if future.result(timeout=_RPC_TIMEOUT_S):
                self._write_json(200, {"session_id": session_id, "closed": True})
            else:
                self._write_json(404, {"error": f"no such session: {session_id}"})

        def _do_delete(self) -> None:
            if urlsplit(self.path).path != "/observability/sessions":
                self._write_json(404, {"error": "not found"})
                return
            if session_history_deleter is None:
                self._write_json(404, {"error": "session deletion is not configured"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._write_json(400, {"error": "invalid content length"})
                return
            if not 1 <= content_length <= _MAX_DELETE_BODY_BYTES:
                self._write_json(400, {"error": "invalid request body size"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._write_json(400, {"error": "invalid json body"})
                return
            raw_session_ids = payload.get("session_ids") if isinstance(payload, dict) else None
            if not isinstance(raw_session_ids, list) or not 1 <= len(raw_session_ids) <= 100:
                self._write_json(400, {"error": "session_ids must contain 1 to 100 ids"})
                return
            if not all(isinstance(session_id, str) and _SESSION_ID.fullmatch(session_id) for session_id in raw_session_ids):
                self._write_json(400, {"error": "invalid session id"})
                return
            if len(set(raw_session_ids)) != len(raw_session_ids):
                self._write_json(400, {"error": "session ids must be unique"})
                return
            active = {session["session_id"] for session in registry.list_sessions()}
            selected_active = sorted(active.intersection(raw_session_ids))
            if selected_active:
                self._write_json(409, {"error": "active sessions cannot be deleted", "session_ids": selected_active})
                return
            future = asyncio.run_coroutine_threadsafe(
                session_history_deleter(raw_session_ids), loop
            )
            self._write_json(200, future.result(timeout=_RPC_TIMEOUT_S))

    return ControlPlaneHandler


async def _list_sessions(registry: EndpointSessionRegistry) -> list[dict]:
    return registry.list_sessions()


def _is_loopback_host(authority: str) -> bool:
    try:
        parsed = urlsplit(f"//{authority}")
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    if hostname is None or parsed.username is not None or parsed.password is not None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_loopback_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    return _is_loopback_host(parsed.netloc)


def start(
    registry: EndpointSessionRegistry,
    *,
    diagnostics: DiagnosticsQuery | None = None,
    voice_previewer: VoicePreviewer | None = None,
    session_conversation_reader: SessionConversationReader | None = None,
    session_history_deleter: SessionHistoryDeleter | None = None,
    avatar_asset_handler: AvatarAssetHandler | None = None,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> ControlPlaneServer:
    """Starts the control plane on a background daemon thread.

    Must be called from within the running asyncio event loop that owns
    `registry` — the returned server bridges back onto that loop for every
    request. Caller owns shutdown: `server.shutdown()` is safe to call
    from another thread (e.g. the event loop thread, during teardown).
    """
    loop = asyncio.get_running_loop()
    avatar_requests = _AvatarRequestTracker(loop)
    server = ControlPlaneServer(
        (host, port),
        _build_handler(
            registry,
            loop,
            avatar_requests,
            diagnostics,
            voice_previewer,
            session_conversation_reader,
            session_history_deleter,
            avatar_asset_handler,
        ),
        avatar_requests=avatar_requests,
    )
    thread = threading.Thread(
        target=server.serve_forever, name="server-control-plane", daemon=True
    )
    thread.start()
    logger.info("control plane listening on http://%s:%d", host, port)
    return server


def _diagnostics_window(query: str) -> DiagnosticsWindow:
    parameters = parse_qs(query)
    raw_minutes = parameters.get("minutes", ["60"])[0]
    try:
        minutes = int(raw_minutes)
    except ValueError as error:
        raise ValueError("minutes must be an integer") from error
    if not 1 <= minutes <= 60 * 24 * 30:
        raise ValueError("minutes must be between 1 and 43200")
    return DiagnosticsWindow.last(timedelta(minutes=minutes))


def _session_limit(query: str) -> int:
    parameters = parse_qs(query)
    raw_limit = parameters.get("limit", ["50"])[0]
    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise ValueError("limit must be an integer") from error
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    return limit
