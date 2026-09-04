from __future__ import annotations

import json
import os
import sys
import time


def emit(value: dict) -> None:
    print(json.dumps(value), flush=True)


def main() -> None:
    session_id = "session-unknown"
    if "--session-id" in sys.argv:
        session_id = sys.argv[sys.argv.index("--session-id") + 1]
    emit({"type": "system", "subtype": "init", "session_id": session_id})
    if os.environ.get("CLAUDE_FIXTURE_SCENARIO") == "slow":
        time.sleep(60)
        return
    for text in ("Working", " done."):
        emit(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": text},
                },
            }
        )
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": session_id,
            "result": "Working done.",
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
    )


if __name__ == "__main__":
    main()
