"""`EndpointSessionRegistry`: owns the hello/resume handshake for every new
physical connection and the grace-period timer that decides how long a
detached `InMemoryEndpointSession` waits for a reattach before being closed
for good. See CONTEXT.md — Endpoint Session,
docs/adr/0019-endpoint-session-reconnect-resume.md.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.transport.base import AuthenticatedTransportIdentity, TransportAdapter
from server.transport.frames import InboundFrame, SessionAckFrame, SessionHelloFrame
from server.voice_session.protocol import ProtocolIncompatible, VoiceSessionFailureFrame

logger = logging.getLogger(__name__)

DEFAULT_GRACE_PERIOD_S = 60.0
DEFAULT_BUFFER_CAPACITY = 256


class _SessionRuntime(Protocol):
    async def run(self) -> None: ...


ThreadAuthorizer = Callable[
    [AuthenticatedTransportIdentity, str], Awaitable[bool]
]
ContinuationAuthorizer = Callable[
    [AuthenticatedTransportIdentity, str, str], Awaitable[bool]
]
FreshSessionAdmitter = Callable[
    [InMemoryEndpointSession, AuthenticatedTransportIdentity], Awaitable[bool]
]


@dataclass
class _Entry:
    session: InMemoryEndpointSession
    protocol_version: int
    resume_token_hash: bytes | None
    endpoint_identity: AuthenticatedTransportIdentity | None
    runtime: _SessionRuntime | None = None
    runtime_task: asyncio.Task[None] | None = None
    grace_task: asyncio.Task[None] | None = None


async def _prepend(
    first: InboundFrame, rest: AsyncIterator[InboundFrame]
) -> AsyncIterator[InboundFrame]:
    yield first
    async for frame in rest:
        yield frame


class EndpointSessionRegistry:
    def __init__(
        self,
        *,
        grace_period_s: float = DEFAULT_GRACE_PERIOD_S,
        buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
        supported_protocol_versions: tuple[int, ...] = (1,),
        development_identity: AuthenticatedTransportIdentity | None = None,
        thread_authorizer: ThreadAuthorizer | None = None,
        continuation_authorizer: ContinuationAuthorizer | None = None,
        fresh_session_admitter: FreshSessionAdmitter | None = None,
    ) -> None:
        if not supported_protocol_versions or any(
            version < 1 for version in supported_protocol_versions
        ):
            raise ValueError("supported protocol versions must be positive")
        self._grace_period_s = grace_period_s
        self._buffer_capacity = buffer_capacity
        self._supported_protocol_versions = supported_protocol_versions
        self._development_identity = development_identity
        self._thread_authorizer = thread_authorizer
        self._continuation_authorizer = continuation_authorizer
        self._fresh_session_admitter = fresh_session_admitter
        self._entries: dict[str, _Entry] = {}
        self._default_heartbeat_interval_ms = 30_000
        if development_identity is not None and 2 in supported_protocol_versions:
            logger.warning(
                "EndpointSessionRegistry is using an unsafe fixed development identity; "
                "do not use this mode for a production endpoint"
            )

    async def handle_connection(
        self,
        transport: TransportAdapter,
        build_runtime: Callable[[InMemoryEndpointSession], _SessionRuntime],
    ) -> None:
        frame_iterator = transport.receive()
        try:
            first_frame = await frame_iterator.__anext__()
        except StopAsyncIteration:
            return

        hello = first_frame if isinstance(first_frame, SessionHelloFrame) else None
        if isinstance(first_frame, SessionHelloFrame):
            resume_session_id = first_frame.resume_session_id
            try:
                protocol_version = self._negotiate_protocol(first_frame)
            except ProtocolIncompatible:
                await transport.send(
                    VoiceSessionFailureFrame(
                        code="protocol_incompatible",
                        phase="starting",
                        retryable=False,
                        session_disposition="close",
                        safe_message="客户端版本不受支持，请升级后重试。",
                    )
                )
                await transport.close()
                return
        else:
            resume_session_id = None
            protocol_version = 1
            frame_iterator = _prepend(first_frame, frame_iterator)

        endpoint_identity = self._transport_identity(transport)
        if protocol_version == 2 and endpoint_identity is None:
            await self._reject_authentication(transport, reconnecting=False)
            return

        entry = self._entries.get(resume_session_id) if resume_session_id else None
        if (
            protocol_version == 2
            and hello is not None
            and hello.previous_voice_session_id is not None
            and (
                resume_session_id is not None
                or hello.requested_thread_id is None
            )
        ):
            await self._reject_authentication(transport, reconnecting=False)
            return
        if (
            protocol_version == 2
            and hello is not None
            and hello.previous_voice_session_id is not None
            and endpoint_identity is not None
            and not await self._can_continue_session(
                endpoint_identity,
                hello.previous_voice_session_id,
                hello.requested_thread_id or "",
            )
        ):
            await self._reject_authentication(transport, reconnecting=False)
            return
        thread_to_authorize = None
        if protocol_version == 2 and endpoint_identity is not None:
            if entry is not None:
                existing_thread = entry.session.authorized_thread_id
                if existing_thread != entry.session.session_id:
                    thread_to_authorize = existing_thread
            elif hello is not None:
                thread_to_authorize = hello.requested_thread_id
        if thread_to_authorize is not None and not await self._can_access_thread(
            endpoint_identity,
            thread_to_authorize,
        ):
            await self._reject_authentication(
                transport,
                reconnecting=resume_session_id is not None,
            )
            return
        if (
            resume_session_id is not None
            and protocol_version == 2
            and not self._can_resume_v2(
                entry,
                hello=hello,
                protocol_version=protocol_version,
                endpoint_identity=endpoint_identity,
            )
        ):
            await transport.send(
                VoiceSessionFailureFrame(
                    code="resume_rejected",
                    phase="reconnecting",
                    retryable=False,
                    session_disposition="continuation_required",
                    safe_message="无法恢复原会话，请继续开启新会话。",
                )
            )
            await transport.close()
            return
        if entry is not None:
            await self._resume(
                entry,
                transport,
                frame_iterator,
                hello=hello,
                protocol_version=protocol_version,
            )
            closed = await entry.session.wait_until_detached_or_closed()
        else:
            entry = await self._start_fresh(
                transport,
                frame_iterator,
                build_runtime,
                client_hello=hello,
                protocol_version=protocol_version,
                endpoint_identity=endpoint_identity,
            )
            if entry is None:
                return
            closed = await entry.session.wait_until_detached_or_closed()

        if (
            not closed
            and getattr(transport, "closed_normally", False)
        ):
            await entry.session.close()
            closed = True
        if closed:
            logger.info("session %s closed", entry.session.session_id)
            self._entries.pop(entry.session.session_id, None)
        else:
            logger.info("session %s detached; grace timer started", entry.session.session_id)
            detached = getattr(entry.runtime, "detached", None)
            if detached is not None:
                await detached()
            self._start_grace_timer(entry.session.session_id)

    async def _resume(
        self,
        entry: _Entry,
        transport: TransportAdapter,
        frame_iterator: AsyncIterator[InboundFrame],
        *,
        hello: SessionHelloFrame | None = None,
        protocol_version: int = 1,
    ) -> None:
        if entry.grace_task is not None and not entry.grace_task.done():
            entry.grace_task.cancel()
        entry.grace_task = None
        await entry.session.attach(transport, frame_iterator)
        if hello is not None:
            entry.session.set_client_hello(hello)
        resume_token = self._new_resume_token() if protocol_version == 2 else None
        entry.resume_token_hash = (
            self._hash_resume_token(resume_token) if resume_token is not None else None
        )
        await transport.send(
            SessionAckFrame(
                session_id=entry.session.session_id,
                resumed=True,
                output_epoch=entry.session.output_epoch,
                resume_token=resume_token,
                protocol_version=protocol_version,
                thread_id=entry.session.authorized_thread_id,
                previous_voice_session_id=entry.session.previous_voice_session_id,
            )
        )
        logger.info("session %s resumed", entry.session.session_id)

    async def _start_fresh(
        self,
        transport: TransportAdapter,
        frame_iterator: AsyncIterator[InboundFrame],
        build_runtime: Callable[[InMemoryEndpointSession], _SessionRuntime],
        client_hello: SessionHelloFrame | None = None,
        protocol_version: int = 1,
        endpoint_identity: AuthenticatedTransportIdentity | None = None,
    ) -> _Entry | None:
        session_id = str(uuid4())
        session = InMemoryEndpointSession(
            session_id,
            transport,
            frame_iterator,
            buffer_capacity=self._buffer_capacity,
            buffer_outbound_frames=protocol_version == 1,
            authenticated_identity=endpoint_identity,
            authorized_thread_id=(
                client_hello.requested_thread_id
                if client_hello is not None
                else None
            ),
            previous_voice_session_id=(
                client_hello.previous_voice_session_id
                if client_hello is not None
                else None
            ),
        )
        if client_hello is not None:
            session.set_client_hello(client_hello)
        if self._fresh_session_admitter is not None and endpoint_identity is not None:
            try:
                admitted = await self._fresh_session_admitter(session, endpoint_identity)
            except Exception:
                logger.exception("endpoint session admission failed")
                admitted = False
            if not admitted:
                await transport.send(
                    VoiceSessionFailureFrame(
                        code="authentication_failed",
                        phase="starting",
                        retryable=False,
                        session_disposition="close",
                        safe_message="语音会话准入已过期，请重新开始。",
                    )
                )
                await transport.close()
                return None
        resume_token = self._new_resume_token() if protocol_version == 2 else None
        entry = _Entry(
            session=session,
            protocol_version=protocol_version,
            resume_token_hash=(
                self._hash_resume_token(resume_token)
                if resume_token is not None
                else None
            ),
            endpoint_identity=endpoint_identity,
        )
        self._entries[session_id] = entry
        await transport.send(
            SessionAckFrame(
                session_id=session_id,
                resumed=False,
                output_epoch=session.output_epoch,
                resume_token=resume_token,
                protocol_version=protocol_version,
                heartbeat_interval_ms=self._default_heartbeat_interval_ms,
                thread_id=session.authorized_thread_id,
                previous_voice_session_id=session.previous_voice_session_id,
            )
        )
        logger.info("session %s started", session_id)
        try:
            runtime = build_runtime(session)
        except Exception:
            logger.exception("session %s runtime construction failed", session_id)
            self._entries.pop(session_id, None)
            await session.send(
                VoiceSessionFailureFrame(
                    code="provider_unavailable",
                    phase="starting",
                    retryable=False,
                    session_disposition="close",
                    safe_message="语音服务暂时不可用，请稍后手动重试。",
                )
            )
            await session.close()
            return None
        entry.runtime = runtime
        task = asyncio.create_task(runtime.run())
        entry.runtime_task = task
        task.add_done_callback(functools.partial(_log_runtime_task_result, session_id))
        return entry

    def _negotiate_protocol(self, hello: SessionHelloFrame) -> int:
        if hello.supported_protocol_versions is None:
            client_versions = {hello.protocol_version}
        else:
            client_versions = set(hello.supported_protocol_versions)
        for version in self._supported_protocol_versions:
            if version in client_versions:
                return version
        raise ProtocolIncompatible("client and server have no shared protocol version")

    @staticmethod
    def _can_resume_v2(
        entry: _Entry | None,
        *,
        hello: SessionHelloFrame | None,
        protocol_version: int,
        endpoint_identity: AuthenticatedTransportIdentity | None,
    ) -> bool:
        if (
            entry is None
            or hello is None
            or hello.resume_token is None
            or entry.resume_token_hash is None
            or entry.protocol_version != protocol_version
            or not entry.session.is_detached
            or endpoint_identity is None
            or entry.endpoint_identity != endpoint_identity
            or (
                hello.requested_thread_id is not None
                and hello.requested_thread_id != entry.session.authorized_thread_id
            )
            or hello.previous_voice_session_id is not None
        ):
            return False
        return hmac.compare_digest(
            entry.resume_token_hash,
            EndpointSessionRegistry._hash_resume_token(hello.resume_token),
        )

    @staticmethod
    def _new_resume_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _hash_resume_token(token: str) -> bytes:
        return hashlib.sha256(token.encode()).digest()

    def _transport_identity(
        self, transport: TransportAdapter
    ) -> AuthenticatedTransportIdentity | None:
        trusted = getattr(transport, "authenticated_identity", None)
        if isinstance(trusted, AuthenticatedTransportIdentity):
            return trusted
        return self._development_identity

    async def _can_access_thread(
        self,
        identity: AuthenticatedTransportIdentity,
        thread_id: str,
    ) -> bool:
        return self._thread_authorizer is not None and await self._thread_authorizer(
            identity,
            thread_id,
        )

    async def _can_continue_session(
        self,
        identity: AuthenticatedTransportIdentity,
        previous_voice_session_id: str,
        thread_id: str,
    ) -> bool:
        return (
            self._continuation_authorizer is not None
            and await self._continuation_authorizer(
                identity,
                previous_voice_session_id,
                thread_id,
            )
        )

    @staticmethod
    async def _reject_authentication(
        transport: TransportAdapter,
        *,
        reconnecting: bool,
    ) -> None:
        await transport.send(
            VoiceSessionFailureFrame(
                code="authentication_failed",
                phase="reconnecting" if reconnecting else "starting",
                retryable=False,
                session_disposition=(
                    "continuation_required" if reconnecting else "close"
                ),
                safe_message="连接身份验证失败。",
            )
        )
        await transport.close()

    def list_sessions(self) -> list[dict]:
        """Snapshot of currently tracked sessions, for the control plane
        (server/control_plane/http.py)."""
        return [
            {
                "session_id": session_id,
                "detached": entry.grace_task is not None and not entry.grace_task.done(),
                "age_s": round(entry.session.age_s, 3),
                "idle_s": round(entry.session.idle_s, 3),
                "has_client_hello": entry.session.client_hello is not None,
            }
            for session_id, entry in self._entries.items()
        ]

    async def close_session(self, session_id: str) -> bool:
        """Force-closes a tracked session immediately, skipping its grace
        period. Returns whether a session was found."""
        entry = self._entries.pop(session_id, None)
        if entry is None:
            return False
        if entry.grace_task is not None and not entry.grace_task.done():
            entry.grace_task.cancel()
        logger.info("session %s force-closed via control plane", session_id)
        await entry.session.close()
        return True

    async def drain(self, *, deadline_s: float = 15.0) -> tuple[str, ...]:
        """Close every live Session and bound process-shutdown cleanup."""

        if deadline_s <= 0:
            raise ValueError("Endpoint Session drain deadline must be positive")
        entries = tuple(self._entries.items())
        self._entries.clear()
        tasks: dict[asyncio.Task[None], str] = {}
        for session_id, entry in entries:
            if entry.grace_task is not None and not entry.grace_task.done():
                entry.grace_task.cancel()
            tasks[asyncio.create_task(entry.session.close())] = session_id
            if entry.runtime_task is not None and not entry.runtime_task.done():
                tasks[entry.runtime_task] = session_id
        if not tasks:
            return ()
        done, pending = await asyncio.wait(tasks, timeout=deadline_s)
        degraded = {tasks[task] for task in pending}
        for task in done:
            if task.cancelled() or task.exception() is not None:
                degraded.add(tasks[task])
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return tuple(sorted(degraded))

    def _start_grace_timer(self, session_id: str) -> None:
        entry = self._entries.get(session_id)
        if entry is None:
            return
        if entry.grace_task is not None and not entry.grace_task.done():
            return
        entry.grace_task = asyncio.create_task(self._grace_timeout(session_id))

    async def _grace_timeout(self, session_id: str) -> None:
        await asyncio.sleep(self._grace_period_s)
        entry = self._entries.pop(session_id, None)
        if entry is not None:
            logger.info("session %s grace period expired; closing", session_id)
            await entry.session.close()


def _log_runtime_task_result(session_id: str, task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.exception("session %s runtime task failed", session_id, exc_info=error)
