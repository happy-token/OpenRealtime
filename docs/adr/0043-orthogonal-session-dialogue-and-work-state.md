---
status: accepted
---

# Model session lifecycle, dialogue state, and work independently

OpenRealtime will not expand one combined state machine to represent every media, lifecycle, tool, task, confirmation, and output condition. Voice Session Phase owns lifecycle, the existing five-value Dialogue State owns conversational floor control, and a Work Registry tracks correlated fast-tool calls, background tasks, and pending confirmation; Generation remains an independent supersession token. This mirrors the observable GPT Voice separation between session lifecycle, local listening/speaking presentation, and app-server work while avoiding a combinatorial state enum.

## Consequences

- Voice Session Phase is `INACTIVE → STARTING → ACTIVE`, with `RECONNECTING`, `STOPPING`, and `CLOSED` branches.
- Dialogue State remains `IDLE | LISTEN | SPEAK | WAIT | DUAL` and does not encode connection or tool status.
- Work is keyed by `call_id`, `worker_id`, and `confirmation_id`, so independent completions and stale-result checks are explicit.
- Snapshots compose these axes instead of flattening them into one status value.
