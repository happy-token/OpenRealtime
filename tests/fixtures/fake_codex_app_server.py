"""Minimal JSONL Codex App Server fixture used by driver contract tests."""

from __future__ import annotations

import json
import sys


threads: dict[str, dict] = {}
next_thread = 1
next_turn = 1


def send(message: dict) -> None:
    print(json.dumps(message, separators=(",", ":")), flush=True)


def response(request_id: object, result: dict) -> None:
    send({"id": request_id, "result": result})


for raw_line in sys.stdin:
    message = json.loads(raw_line)
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})

    if method == "initialized":
        continue
    if method == "initialize":
        response(request_id, {"serverInfo": {"name": "fake-codex", "version": "1"}})
        continue
    if method == "thread/start":
        thread_id = f"thread-{next_thread}"
        next_thread += 1
        threads[thread_id] = {"id": thread_id, "turns": []}
        response(request_id, {"thread": {"id": thread_id}})
        continue
    if method == "turn/start":
        thread_id = params["threadId"]
        turn_id = f"turn-{next_turn}"
        next_turn += 1
        turn = {"id": turn_id, "status": "inProgress", "items": []}
        threads[thread_id]["turns"].append(turn)
        response(request_id, {"turn": turn})
        send(
            {
                "method": "turn/started",
                "params": {"threadId": thread_id, "turn": turn},
            }
        )
        instruction = " ".join(
            item.get("text", "") for item in params.get("input", []) if isinstance(item, dict)
        )
        if "WAIT_FOR_CANCEL" in instruction:
            continue
        send(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": "message-1",
                    "delta": "FAKE_CODEX_OK",
                },
            }
        )
        send(
            {
                "method": "turn/plan/updated",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "plan": [{"step": "reply", "status": "completed"}],
                },
            }
        )
        send(
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "tokenUsage": {
                        "total": {
                            "inputTokens": 10,
                            "cachedInputTokens": 2,
                            "outputTokens": 3,
                        }
                    },
                },
            }
        )
        turn.update(
            {
                "status": "completed",
                "items": [
                    {
                        "id": "message-1",
                        "type": "agentMessage",
                        "text": "FAKE_CODEX_OK",
                    }
                ],
            }
        )
        send(
            {
                "method": "turn/completed",
                "params": {"threadId": thread_id, "turn": turn},
            }
        )
        continue
    if method == "thread/read":
        thread = threads[params["threadId"]]
        response(request_id, {"thread": thread})
        continue
    if method == "thread/resume":
        thread = threads[params["threadId"]]
        response(request_id, {"thread": thread})
        continue
    if method == "turn/steer":
        response(request_id, {"turnId": params["expectedTurnId"]})
        continue
    if method == "turn/interrupt":
        thread_id = params["threadId"]
        turn_id = params["turnId"]
        turn = next(turn for turn in threads[thread_id]["turns"] if turn["id"] == turn_id)
        turn.update({"status": "interrupted", "items": []})
        response(request_id, {})
        send(
            {
                "method": "turn/completed",
                "params": {"threadId": thread_id, "turn": turn},
            }
        )
        continue
    if method == "thread/unsubscribe":
        response(request_id, {})
        continue

    if request_id is not None:
        send(
            {
                "id": request_id,
                "error": {"code": -32601, "message": f"unsupported method: {method}"},
            }
        )
