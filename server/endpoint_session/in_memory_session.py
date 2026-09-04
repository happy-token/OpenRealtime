"""`InMemoryEndpointSession`: the framework's shipped `EndpointSession`
conformer. Single-process only (same caveat as `InMemoryDriver`/
`InMemoryDeviceFleet`) — session state lives in this object, not in any
external store, so it cannot survive a process restart or be resumed
against a different server process. See
docs/adr/0019-endpoint-session-reconnect-resume.md.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator

from server.transport.base import (
    AuthenticatedTransportIdentity,
    TransportAdapter,
    TransportDisconnected,
)
from server.transport.frames import InboundFrame, OutboundFrame, SessionHelloFrame

logger = logging.getLogger(__name__)


class InMemoryEndpointSession:
    def __init__(
        self,
        session_id: str,
        transport: TransportAdapter,
        frame_iterator: AsyncIterator[InboundFrame],
        *,
        buffer_capacity: int = 256,
        buffer_outbound_frames: bool = True,
        authenticated_identity: AuthenticatedTransportIdentity | None = None,
        authorized_thread_id: str | None = None,
        previous_voice_session_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self._transport: TransportAdapter | None = transport
        self._frame_iterator: AsyncIterator[InboundFrame] | None = frame_iterator
        self._buffer_capacity = buffer_capacity
        self._buffer_outbound_frames = buffer_outbound_frames
        self._buffer: deque[OutboundFrame] = deque()
        self._authenticated_identity = authenticated_identity
        self._authorized_thread_id = authorized_thread_id or session_id
        self._previous_voice_session_id = previous_voice_session_id
        self._client_hello: SessionHelloFrame | None = None
        self._created_at = time.monotonic()
        self._last_activity_at = self._created_at
        self._reattached = asyncio.Event()
        self._detached_event = asyncio.Event()
        self._closed = asyncio.Event()
        self._send_lock = asyncio.Lock()
        """Serializes `send` against itself and against `_flush_buffer`.

        Two independent writers are possible during concurrent turn execution:
        the runtime frame loop (which sends the barge-in cancel frame) and an
        in-flight turn task (which streams audio chunks). Without
        this lock, `_flush_buffer` replaying buffered frames on reattach can
        also interleave with a live `send`, putting older buffered frames
        *after* newer live ones on the wire — the one ordering guarantee
        ADR-0019's replay behavior depends on.
        """

    async def receive(self) -> AsyncIterator[InboundFrame]:
        while not self._closed.is_set():
            frame_iterator = self._frame_iterator
            if frame_iterator is not None:
                async for frame in frame_iterator:
                    self._touch_activity()
                    yield frame
                if self._closed.is_set():
                    return
                await self.detach()
            await self._wait_reattached_or_closed()

    async def send(self, frame: OutboundFrame) -> None:
        async with self._send_lock:
            transport = self._transport
            if transport is not None:
                try:
                    await transport.send(frame)
                    self._touch_activity()
                    return
                except TransportDisconnected:
                    if self._transport is transport:
                        self._transport = None
                        self._frame_iterator = None
                        self._reattached.clear()
                        self._detached_event.set()
            if not self._buffer_outbound_frames:
                logger.info(
                    "Endpoint session %s discarded detached raw frame type=%r; "
                    "v2 recovery uses semantic state",
                    self.session_id,
                    frame.type,
                )
                return
            if len(self._buffer) >= self._buffer_capacity:
                dropped = self._buffer.popleft()
                logger.warning(
                    "Endpoint session %s outbound buffer full (capacity=%d); "
                    "dropping oldest buffered frame type=%r",
                    self.session_id,
                    self._buffer_capacity,
                    dropped.type,
                )
            self._buffer.append(frame)

    async def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        transport = self._transport
        self._transport = None
        self._frame_iterator = None
        if transport is not None:
            await transport.close()

    async def attach(
        self, transport: TransportAdapter, frame_iterator: AsyncIterator[InboundFrame] | None = None
    ) -> None:
        self._transport = transport
        self._frame_iterator = frame_iterator if frame_iterator is not None else transport.receive()
        self._touch_activity()
        self._detached_event.clear()
        await self._flush_buffer()
        self._reattached.set()

    async def detach(self) -> None:
        if self._transport is None:
            return
        self._transport = None
        self._frame_iterator = None
        self._reattached.clear()
        self._detached_event.set()

    async def wait_until_detached_or_closed(self) -> bool:
        """Blocks until this attach cycle ends. Returns True if the session
        was closed for good, False if it merely detached (and may resume)."""
        detached_task = asyncio.ensure_future(self._detached_event.wait())
        closed_task = asyncio.ensure_future(self._closed.wait())
        try:
            await asyncio.wait({detached_task, closed_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (detached_task, closed_task):
                if not task.done():
                    task.cancel()
        return self._closed.is_set()

    async def _flush_buffer(self) -> None:
        async with self._send_lock:
            transport = self._transport
            if transport is None:
                return
            while self._buffer:
                frame = self._buffer.popleft()
                await transport.send(frame)
                self._touch_activity()

    async def _wait_reattached_or_closed(self) -> None:
        reattached_task = asyncio.ensure_future(self._reattached.wait())
        closed_task = asyncio.ensure_future(self._closed.wait())
        try:
            await asyncio.wait({reattached_task, closed_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (reattached_task, closed_task):
                if not task.done():
                    task.cancel()
        self._reattached.clear()

    def set_client_hello(self, frame: SessionHelloFrame) -> None:
        self._client_hello = frame

    @property
    def client_hello(self) -> SessionHelloFrame | None:
        return self._client_hello

    @property
    def authenticated_identity(self) -> AuthenticatedTransportIdentity | None:
        return self._authenticated_identity

    @property
    def authorized_thread_id(self) -> str:
        return self._authorized_thread_id

    @property
    def previous_voice_session_id(self) -> str | None:
        return self._previous_voice_session_id

    @property
    def is_detached(self) -> bool:
        return self._transport is None and not self._closed.is_set()

    @property
    def age_s(self) -> float:
        return max(0.0, time.monotonic() - self._created_at)

    @property
    def idle_s(self) -> float:
        return max(0.0, time.monotonic() - self._last_activity_at)

    def _touch_activity(self) -> None:
        self._last_activity_at = time.monotonic()
