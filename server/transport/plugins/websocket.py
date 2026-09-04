"""Raw WebSocket Transport Adapter — one of two real conformers shipped so
far (see transport/plugins/udp.py for the other). RTC, MQTT, and direct LiveKit
integration remain contract-only per CONTEXT.md's Transport Adapter entry.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from http.cookies import CookieError, SimpleCookie
from typing import Protocol

from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as _serve
from websockets.exceptions import ConnectionClosed

from server.transport.base import AuthenticatedTransportIdentity, TransportDisconnected
from server.transport.frame_parsing import parse_inbound_frame
from server.transport.frames import (
    InboundFrame,
    OutboundFrame,
    SessionHelloFrame,
    VoiceSessionPhaseChangedFrame,
)
from server.voice_session.protocol import VoiceSessionFailureFrame

logger = logging.getLogger(__name__)


class WebSocketAuthenticator(Protocol):
    def authenticate(
        self, headers: Mapping[str, str]
    ) -> AuthenticatedTransportIdentity | None: ...


class StaticBearerWebSocketAuthenticator:
    """Small single-principal authenticator for a trusted proxy or secure cookie.

    Multi-user deployments should provide their own ``WebSocketAuthenticator``
    backed by the application's login/session authority.
    """

    def __init__(
        self,
        *,
        token: str,
        identity: AuthenticatedTransportIdentity,
        cookie_name: str = "openrealtime_endpoint_token",
    ) -> None:
        if len(token) < 32:
            raise ValueError("WebSocket bearer token must be at least 32 characters")
        if not cookie_name:
            raise ValueError("WebSocket auth cookie name must be non-empty")
        self._token = token
        self._identity = identity
        self._cookie_name = cookie_name

    def authenticate(
        self, headers: Mapping[str, str]
    ) -> AuthenticatedTransportIdentity | None:
        authorization = _header(headers, "authorization")
        candidate: str | None = None
        if authorization is not None and authorization.startswith("Bearer "):
            candidate = authorization.removeprefix("Bearer ")
        if candidate is None:
            cookie_header = _header(headers, "cookie")
            if cookie_header is not None:
                cookies = SimpleCookie()
                try:
                    cookies.load(cookie_header)
                except CookieError:
                    return None
                morsel = cookies.get(self._cookie_name)
                candidate = None if morsel is None else morsel.value
        if candidate is None or not hmac.compare_digest(candidate, self._token):
            return None
        return self._identity


class WebSocketTransportAdapter:
    def __init__(
        self,
        connection: ServerConnection,
        *,
        authenticated_identity: AuthenticatedTransportIdentity | None = None,
    ) -> None:
        self._connection = connection
        self.authenticated_identity = authenticated_identity
        self._protocol_version = 1
        self._voice_session_phase = "starting"

    async def receive(self) -> AsyncIterator[InboundFrame]:
        async for raw_message in self._connection:
            frame = parse_inbound_frame(raw_message)
            if frame is None:
                if self._protocol_version == 2:
                    await self.send(
                        VoiceSessionFailureFrame(
                            code="invalid_command",
                            phase=self._voice_session_phase,
                            retryable=False,
                            session_disposition="close",
                            safe_message="客户端命令无效，请重新连接后重试。",
                        )
                    )
                    await self.close()
                    return
                continue
            if isinstance(frame, SessionHelloFrame) and (
                frame.protocol_version == 2
                or (
                    frame.supported_protocol_versions is not None
                    and 2 in frame.supported_protocol_versions
                )
            ):
                self._protocol_version = 2
            yield frame

    async def send(self, frame: OutboundFrame) -> None:
        if isinstance(frame, VoiceSessionPhaseChangedFrame):
            self._voice_session_phase = frame.to_phase
        try:
            await self._connection.send(frame.model_dump_json())
        except ConnectionClosed as error:
            raise TransportDisconnected("WebSocket connection closed") from error

    async def close(self) -> None:
        await self._connection.close()


ConnectionHandler = Callable[[WebSocketTransportAdapter], Awaitable[None]]


async def serve(
    handler: ConnectionHandler,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    authenticator: WebSocketAuthenticator | None = None,
) -> None:
    """Run a Raw WebSocket server, dispatching one handler call per connection."""

    async def _on_connection(connection: ServerConnection) -> None:
        identity = None
        if authenticator is not None and connection.request is not None:
            identity = authenticator.authenticate(connection.request.headers)
        await handler(
            WebSocketTransportAdapter(
                connection,
                authenticated_identity=identity,
            )
        )

    async with _serve(_on_connection, host, port) as server:
        await server.serve_forever()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    return next(
        (value for key, value in headers.items() if key.lower() == expected),
        None,
    )
