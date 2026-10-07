"""Actual loopback fixture ownership, including failure during close."""
from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedError

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from tests import browser_recording_playback_fixture as module
from tests.realtime.test_realtime_websocket_bridge import context


async def wait_inactive(fixture) -> None:
    async def wait():
        while fixture.active:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 2)


async def hello(socket) -> None:
    await socket.send(json.dumps({"type": "session_hello"}))
    assert json.loads(await socket.recv())["type"] == "session_ack"
    assert json.loads(await socket.recv())["type"] == "session_capabilities"


async def test_empty_settled_development_connection_can_be_replaced() -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig(state_backend="memory"))
    fixture = module.RecordingRendererFixture(runtime, context())
    try:
        async with serve(fixture.handle, "127.0.0.1", 0) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/voice"
            for _ in range(2):
                async with connect(url) as socket:
                    await hello(socket)
                await wait_inactive(fixture)
            assert fixture.connections == 2
            assert fixture.closed and not fixture.started and fixture.error is None
    finally:
        await runtime.close()


async def test_failed_cleanup_cannot_rebind_the_fixture_owner(monkeypatch) -> None:
    class FaultyClose(module.InMemoryRealtimeConversation):
        async def close(self) -> None:
            await super().close()
            raise RuntimeError("injected conversation cleanup failure")
    monkeypatch.setattr(module, "InMemoryRealtimeConversation", FaultyClose)
    runtime = await build_application_runtime(ApplicationRuntimeConfig(state_backend="memory"))
    fixture = module.RecordingRendererFixture(runtime, context())
    try:
        async with serve(fixture.handle, "127.0.0.1", 0) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/voice"
            async with connect(url) as socket:
                await hello(socket)
            await wait_inactive(fixture)
            assert fixture.error == "injected conversation cleanup failure"
            assert not fixture.closed
            async with connect(url) as replacement:
                with pytest.raises(ConnectionClosedError) as caught:
                    await replacement.recv()
                assert caught.value.rcvd.code == 1013
            assert fixture.connections == 1
    finally:
        await runtime.close()
