import asyncio

from server.transport.frames import AssistantTextFrame, UserTextFrame
from server.transport.plugins.udp import UdpTransportAdapter


class FakeDatagramTransport:
    """Test double standing in for an asyncio.DatagramTransport."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        self.closed = True


def _make_adapter(*raw_messages: bytes) -> UdpTransportAdapter:
    transport = FakeDatagramTransport()
    queue: asyncio.Queue = asyncio.Queue()
    for message in raw_messages:
        queue.put_nowait(message)
    return UdpTransportAdapter(transport, ("127.0.0.1", 9999), queue)


async def _collect(adapter: UdpTransportAdapter) -> list:
    return [frame async for frame in adapter.receive()]


async def test_receive_parses_queued_user_text_datagram():
    adapter = _make_adapter(b'{"type": "user_text", "text": "hello"}')
    await adapter.close()

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="hello")]


async def test_receive_drops_malformed_datagram():
    adapter = _make_adapter(b"not json", b'{"type": "user_text", "text": "ok"}')
    await adapter.close()

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="ok")]


async def test_send_calls_sendto_with_serialized_json_and_peer_address():
    transport = FakeDatagramTransport()
    queue: asyncio.Queue = asyncio.Queue()
    peer_address = ("127.0.0.1", 9999)
    adapter = UdpTransportAdapter(transport, peer_address, queue)

    await adapter.send(AssistantTextFrame(text="hi there", generation=3))

    assert transport.sent == [
        (
            b'{"type":"assistant_text","text":"hi there","generation":3,"emotion":null,"gesture":null}',
            peer_address,
        )
    ]


async def test_close_enqueues_sentinel_ending_receive():
    adapter = _make_adapter()

    await adapter.close()

    frames = await _collect(adapter)
    assert frames == []
