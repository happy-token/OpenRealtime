"""Tests for UdpTransportAdapter's demultiplexing logic — the real, non-trivial
behavior in transport/plugins/udp.py's serve() path. No real socket: _DemuxProtocol's
callbacks (connection_made/datagram_received) are invoked directly, per this
project's convention of unit-testing private wire-protocol logic without
sockets (see tests/speech/test_doubao_asr_protocol.py). serve() itself opens
a real datagram endpoint and is intentionally left untested here. The former
Kernel-based UDP demo was removed until a v2 Voice Session conformer exists.
"""

from server.transport.plugins.udp import UdpTransportAdapter, _DemuxProtocol


class FakeDatagramTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


def _make_protocol() -> tuple[_DemuxProtocol, list[UdpTransportAdapter]]:
    new_peers: list[UdpTransportAdapter] = []
    protocol = _DemuxProtocol(new_peers.append)
    protocol.connection_made(FakeDatagramTransport())
    return protocol, new_peers


async def test_first_datagram_from_new_peer_dispatches_one_new_adapter():
    protocol, new_peers = _make_protocol()

    protocol.datagram_received(b"hello", ("127.0.0.1", 9001))

    assert len(new_peers) == 1
    assert new_peers[0]._peer_address == ("127.0.0.1", 9001)


async def test_second_datagram_from_same_peer_does_not_dispatch_again():
    protocol, new_peers = _make_protocol()
    protocol.datagram_received(b"first", ("127.0.0.1", 9001))

    protocol.datagram_received(b"second", ("127.0.0.1", 9001))

    assert len(new_peers) == 1


async def test_second_datagram_from_same_peer_is_queued_to_same_adapter():
    protocol, new_peers = _make_protocol()
    protocol.datagram_received(b"first", ("127.0.0.1", 9001))
    protocol.datagram_received(b"second", ("127.0.0.1", 9001))
    await new_peers[0].close()

    frames = [raw async for raw in _drain_raw(new_peers[0])]

    assert frames == [b"first", b"second"]


async def test_datagram_from_a_different_peer_dispatches_a_separate_adapter():
    protocol, new_peers = _make_protocol()
    protocol.datagram_received(b"from-a", ("127.0.0.1", 9001))

    protocol.datagram_received(b"from-b", ("127.0.0.1", 9002))

    assert len(new_peers) == 2
    assert new_peers[1]._peer_address == ("127.0.0.1", 9002)


async def _drain_raw(adapter: UdpTransportAdapter):
    while True:
        raw = await adapter._inbound.get()
        if raw is None:
            return
        yield raw
