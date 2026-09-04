"""Scripted stdio ACP agent fixture used by tests/test_acp_driver.py.

Speaks the same NDJSON-over-stdio JSON-RPC 2.0 protocol as a real ACP
backend (e.g. `opencode acp`), spawned as a real subprocess so
`SubprocessAcpTransport` is exercised for real without depending on any
vendor CLI being installed. Behavior is selected via the
`ACP_FIXTURE_SCENARIO` environment variable:

- `success` — one prompt round-trip with two streamed message chunks.
- `permission_gate` — sends a chunk, then blocks the turn on a
  `session/request_permission` request before sending a second chunk that
  echoes the approved optionId, letting tests verify auto-approval.
- `streaming_gate` — sends one chunk, then blocks (a real, unbounded stdin
  read — not a timing race) until it receives a `session/cancel`
  notification, then sends a second chunk and completes normally. Tests
  reuse `AcpAgentSession.cancel()` purely as a deterministic "release the
  gate" signal here, not to model real turn cancellation.
- `cancel_probe` — withholds its result until it receives a
  `session/cancel` notification, then reports `stopReason: "cancelled"`.
- `error` — responds to `session/prompt` with a JSON-RPC error.
- `crash` — exits without responding to `session/prompt`.
"""

from __future__ import annotations

import json
import os
import sys


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _read() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _handle_prompt(scenario: str, message_id: int, session_id: str) -> None:
    if scenario == "crash":
        sys.exit(1)

    if scenario == "error":
        _write({"jsonrpc": "2.0", "id": message_id, "error": {"code": -32000, "message": "backend exploded"}})
        return

    if scenario == "cancel_probe":
        while True:
            message = _read()
            if message is None:
                return
            if message.get("method") == "session/cancel":
                _write(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"text": "cancelled-received"},
                            },
                        },
                    }
                )
                _write({"jsonrpc": "2.0", "id": message_id, "result": {"stopReason": "cancelled"}})
                return

    if scenario == "streaming_gate":
        _write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "Working"}},
                },
            }
        )
        while True:
            message = _read()
            if message is None:
                return
            if message.get("method") == "session/cancel":
                break
        _write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": " on it."}},
                },
            }
        )
        _write({"jsonrpc": "2.0", "id": message_id, "result": {"stopReason": "end_turn"}})
        return

    if scenario == "permission_gate":
        _write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "Working"}},
                },
            }
        )
        permission_request_id = 9001
        _write(
            {
                "jsonrpc": "2.0",
                "id": permission_request_id,
                "method": "session/request_permission",
                "params": {
                    "sessionId": session_id,
                    "toolCall": {"title": "write checkers.html"},
                    "options": [
                        {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"},
                    ],
                },
            }
        )
        permission_response = _read()
        selected = (permission_response or {}).get("result", {}).get("outcome", {}).get("optionId")
        _write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"text": f"approved:{selected}"},
                    },
                },
            }
        )
        _write({"jsonrpc": "2.0", "id": message_id, "result": {"stopReason": "end_turn"}})
        return

    # success (default)
    for text in ("Working", " on it."):
        _write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": session_id,
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": text}},
                },
            }
        )
    _write({"jsonrpc": "2.0", "id": message_id, "result": {"stopReason": "end_turn"}})


def main() -> None:
    scenario = os.environ.get("ACP_FIXTURE_SCENARIO", "success")

    while True:
        message = _read()
        if message is None:
            return
        method = message.get("method")
        message_id = message.get("id")

        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "protocolVersion": 1,
                        "agentCapabilities": {},
                        "agentInfo": {"name": "fake-acp-agent", "version": "0.0.0"},
                    },
                }
            )
        elif method == "session/new":
            _write({"jsonrpc": "2.0", "id": message_id, "result": {"sessionId": "session-1"}})
        elif method == "session/prompt":
            _handle_prompt(scenario, message_id, message["params"]["sessionId"])
        elif method == "session/cancel":
            pass
        elif message_id is not None:
            _write({"jsonrpc": "2.0", "id": message_id, "error": {"code": -32601, "message": f"unhandled method {method}"}})


if __name__ == "__main__":
    main()
