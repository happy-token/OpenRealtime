"""Raw UDP Transport Adapter (stdlib asyncio, no new dependencies) — a real,
loopback-testable wire-level implementation, mirroring
WebSocketTransportAdapter's per-connection shape. UDP has no persistent
connection object, so `serve()` demultiplexes by peer address: the first
datagram from a new address is treated as a new connection and dispatched
to `handler`; subsequent datagrams from that address are queued to the same
adapter. Simplification: an adapter's `close()` stops its own receive loop
only — it does not evict the peer's demux entry, so a genuinely new session
reusing the same address after close is out of scope (never a
production-grade UDP session manager, same caveat as InMemoryDeviceFleet).
See CONTEXT.md — Transport Adapter.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from server.transport.frame_parsing import parse_inbound_frame
from server.transport.frames import InboundFrame, OutboundFrame

logger = logging.getLogger(__name__)

_Address = tuple[str, int]


class UdpTransportAdapter:
    def __init__(
        self,
        transport: asyncio.DatagramTransport,
        peer_address: _Address,
        inbound: asyncio.Queue,
    ) -> None:
        self._transport = transport
        self._peer_address = peer_address
        self._inbound = inbound

    async def receive(self) -> AsyncIterator[InboundFrame]:
        while True:
            raw = await self._inbound.get()
            if raw is None:
                return
            frame = parse_inbound_frame(raw)
            if frame is not None:
                yield frame

    async def send(self, frame: OutboundFrame) -> None:
        self._transport.sendto(frame.model_dump_json().encode("utf-8"), self._peer_address)

    async def close(self) -> None:
        await self._inbound.put(None)


ConnectionHandler = Callable[[UdpTransportAdapter], Awaitable[None]]


class _DemuxProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_new_peer: Callable[[UdpTransportAdapter], None]) -> None:
        self._peers: dict[_Address, asyncio.Queue] = {}
        self._on_new_peer = on_new_peer
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: _Address) -> None:
        queue = self._peers.get(addr)
        if queue is None:
            queue = asyncio.Queue()
            self._peers[addr] = queue
            assert self._transport is not None
            self._on_new_peer(UdpTransportAdapter(self._transport, addr, queue))
        queue.put_nowait(data)


async def serve(handler: ConnectionHandler, *, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run a Raw UDP server, dispatching one handler task per peer address."""
    loop = asyncio.get_running_loop()
    tasks: set[asyncio.Task] = set()

    def _on_new_peer(adapter: UdpTransportAdapter) -> None:
        task = asyncio.create_task(handler(adapter))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _DemuxProtocol(_on_new_peer), local_addr=(host, port)
    )
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()
