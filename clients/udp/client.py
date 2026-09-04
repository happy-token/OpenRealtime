"""Minimal demo client: type a line, get a reply back over UDP.

Simulates a finalized ASR transcript by sending a user_text frame directly
(v1 has no ASR vendor wired in — see CONTEXT.md's Transport Adapter entry).

Run (with the server already running):
    uv run python clients/udp/client.py
"""

from __future__ import annotations

import asyncio
import json

SERVER_ADDRESS = ("127.0.0.1", 8765)


class _ReplyPrintingProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        payload = json.loads(data)
        print(f"assistant: {payload['text']}")


async def main() -> None:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        _ReplyPrintingProtocol, remote_addr=SERVER_ADDRESS
    )
    print(f"Sending to {SERVER_ADDRESS}. Type a message and press Enter (Ctrl+D to quit).")
    try:
        while True:
            try:
                text = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if not text.strip():
                continue

            transport.sendto(json.dumps({"type": "user_text", "text": text}).encode("utf-8"))
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
