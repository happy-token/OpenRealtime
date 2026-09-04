"""Minimal demo client: type a line, get a reply back over the wire.

Simulates a finalized ASR transcript by sending a user_text frame directly
(v1 has no ASR vendor wired in — see CONTEXT.md's Transport Adapter entry).

Run (with the server already running):
    uv run python clients/websocket/client.py
"""

from __future__ import annotations

import asyncio
import json

from websockets.asyncio.client import connect

SERVER_URL = "ws://localhost:8765"


async def main() -> None:
    async with connect(SERVER_URL) as connection:
        print(f"Connected to {SERVER_URL}. Type a message and press Enter (Ctrl+D to quit).")
        while True:
            try:
                text = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if not text.strip():
                continue

            await connection.send(json.dumps({"type": "user_text", "text": text}))
            reply = await connection.recv()
            payload = json.loads(reply)
            print(f"assistant: {payload['text']}")


if __name__ == "__main__":
    asyncio.run(main())
