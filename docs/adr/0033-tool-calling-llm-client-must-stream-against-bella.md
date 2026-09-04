---
status: accepted
---

# Tool-calling LLM client must always request `stream: true`

Manual verification of ADR-0032's wiring fix (`VOICEAGENT_DEMO_TOOLS=1` reaching a real
`ToolCallingBrain` in the live demo) surfaced a second, independent bug once the wiring actually
ran against Bella for the first time: every `get_current_datetime` request came back as an
explicit error-fallback reply instead of a real answer.

Server logs showed the root cause directly: `openai_compatible_tool_calling_llm_client.py`'s
request to `https://bella-openapi.ke.com/v1` failed with `HTTP 400`. Reproducing the exact
request by hand and reading the (previously discarded) response body gave Bella's real error:

```
{"error":{"code":"bad_response_status_code","httpCode":400,
  "message":"Stream must be set to true", ...}}
```

`OpenAiCompatibleToolCallingLlmClient` (ADR-0029) never set `stream` in its request body, so it
defaulted to `false` — a plain request/response call. Bella's gateway rejects that outright. The
sibling `OpenAiCompatibleLlmClient` (used by `ChatBrain`, ADR-0009) already always sends
`stream: true` and works fine against the same gateway; the tool-calling client was simply built
without that requirement, and nothing had ever exercised it against Bella live until ADR-0032's
wiring fix made that path reachable for the first time.

## Fix

`OpenAiCompatibleToolCallingLlmClient` now always sends `stream: true`, matching
`OpenAiCompatibleLlmClient`'s convention. Deciding tool-call-vs-final-text still needs the whole
message, not a token stream, so `_read_sse_stream()` fully accumulates the SSE response — both
`delta.content` fragments and `delta.tool_calls` fragments (keyed by the stream's `index`, since a
tool call's name arrives once and its `arguments` string is fragmented across many chunks) —
before `complete()` returns anything to `ToolCallingBrain`. Nothing is streamed onward to the
caller; this is purely an internal transport change to satisfy Bella's gateway.

Verified live against Bella directly (bypassing the demo) that the fixed request body no longer
400s and returns a correctly-parsed `tool_calls` delta stream, then re-verified end-to-end through
the running `pnpm dev` server: `get_current_datetime` now returns a real, correctly-grounded
answer, and a search-style query correctly round-trips through both `ToolCallingBrain.respond()`
calls (confirmed via two distinct "tool-calling LLM request ... completed" log lines per turn) and
resolves `search_web` to `DeterministicWebSearch`'s accepted "No results found." stub — the
model's declining-to-search reply reflects that stub content, not a failure to call the tool.

## Also fixed

`tests/test_openai_compatible_tool_calling_llm_client.py` previously faked a plain JSON
`{"choices": [{"message": ...}]}` response, which no longer matches what the client parses. Fake
responses are now SSE delta streams built from the same non-streaming message shape the tests
already reasoned about, plus one new test asserting `stream: true` is always sent and one
asserting tool-call `arguments` fragments spread across multiple chunks are concatenated, not
overwritten.
