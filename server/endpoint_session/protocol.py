"""Endpoint Session: the Seam owning a logical session's identity and
continuity independent of any one physical `TransportAdapter` connection.

`EndpointSession` conforms to `TransportAdapter` itself (`receive`/`send`/
`close`) — a Voice Session runtime handed one needs no code of its own to
benefit from reconnect/resume; it is structurally indistinguishable from a
raw transport. `attach`/`detach` are the extra
surface `EndpointSessionRegistry` uses to move a session across physical
connections. See CONTEXT.md — Endpoint Session,
docs/adr/0019-endpoint-session-reconnect-resume.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from server.transport.base import TransportAdapter
from server.transport.frames import InboundFrame, OutboundFrame


class EndpointSession(Protocol):
    session_id: str

    def receive(self) -> AsyncIterator[InboundFrame]: ...

    async def send(self, frame: OutboundFrame) -> None: ...

    async def close(self) -> None: ...

    async def attach(
        self, transport: TransportAdapter, frame_iterator: AsyncIterator[InboundFrame] | None = None
    ) -> None: ...

    async def detach(self) -> None: ...
