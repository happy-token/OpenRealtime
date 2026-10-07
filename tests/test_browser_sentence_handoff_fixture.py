"""The browser test fixture cannot transfer ownership between live sockets."""

import asyncio
import json
import signal
import sys
from urllib.request import urlopen

from websockets.asyncio.client import connect


async def test_fixture_rejects_overlap_until_original_handler_fully_closes():
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "tests.browser_sentence_handoff_fixture",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(5):
            ready = json.loads(await process.stdout.readline())
        port = ready["port"]
        async def evidence(action="evidence"):
            def read():
                with urlopen(f"http://127.0.0.1:{port}/{action}", timeout=1) as response:
                    payload = response.read()
                    assert response.headers.get("Connection") == "close"
                    assert response.headers.get("Content-Length") is not None
                    assert int(response.headers["Content-Length"]) == len(payload)
                    return json.loads(payload)
            return await asyncio.to_thread(read)
        async with connect(f"ws://127.0.0.1:{port}/voice") as first:
            await first.send(json.dumps({"type": "session_hello"}))
            assert json.loads(await asyncio.wait_for(first.recv(), 2))["type"] == "session_ack"
            await evidence("start")
            async with asyncio.timeout(2):
                async for raw in first:
                    if json.loads(raw)["type"] == "assistant_response_completed":
                        break
            original = await evidence()
            async with connect(f"ws://127.0.0.1:{port}/voice") as overlap:
                await asyncio.wait_for(overlap.wait_closed(), 2)
                assert overlap.close_code == 1013
            assert await evidence() == original
        async with asyncio.timeout(2):
            while not (await evidence()).get("closed"):
                await asyncio.sleep(0)
        # Only after full closure can another handler obtain the test owners.
        async with connect(f"ws://127.0.0.1:{port}/voice?kind=speech") as replacement:
            await replacement.send(json.dumps({"type": "session_hello"}))
            async with asyncio.timeout(2):
                assert json.loads(await replacement.recv())["type"] == "session_ack"
            assert not (await evidence()).get("closed", False)
    finally:
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            raise AssertionError(f"fixture failed to close: {stderr.decode()}") from None
        assert process.returncode == 0, (stdout.decode(), stderr.decode())
