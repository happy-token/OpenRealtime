---
status: accepted
---

# Wire tool-calling + web search into the live demo

User report: web search "还不太对，无法使用" (broken/unusable), with a request to check
whether the wiring is misaligned with the sibling reference project
the sibling reference project.

It wasn't a protocol bug. `server/web_search/plugins/byte_web_search.py` calls the same
endpoint, request body, and headers as realtime's `byte_search.py`, and parses the same
response shape. The actual bug was the same "built but never wired" pattern already found and
fixed for datetime grounding (ADR-0030) and for Silero VAD/semantic EOT/semantic interruption
(ADR-0035): `demos/voice_web_server.py` — the server `pnpm dev` runs — hardcoded
`Router(ChatBrain(llm_client))` and never imported or constructed `ToolCallingBrain`,
`WebSearchToolSource`, `ClockToolSource`, or `ByteWebSearch`, and never read
`VOICEAGENT_DEMO_TOOLS` at all. `.env` already had `VOICEAGENT_DEMO_TOOLS=1` set — someone had
already tried to turn this on, and it silently had zero effect, because only the secondary demo
entrypoint, `demos/basic_ws_server.py`, actually reads that env var.

## Fix

Ported `basic_ws_server.py`'s exact env-var-gated wiring pattern into `voice_web_server.py`:
`_build_brain(llm_client)` returns plain `ChatBrain` unless `VOICEAGENT_DEMO_TOOLS` is set, in
which case it returns `ToolCallingBrain` wired to a `ToolRegistry([ClockToolSource(),
WebSearchToolSource(_build_web_search())])`. `_build_kernel` now calls
`Router(_build_brain(llm_client))` instead of `Router(ChatBrain(llm_client))`.

## Tool-calling LLM credentials: three tiers, not two

`basic_ws_server.py`'s `_build_tool_calling_llm_client()` only checks
`VOICEAGENT_LLM_API_KEY`, since that demo has no separate first-class backend. But
`voice_web_server.py` already treats Bella (`API_KEY`/`BELLA_BASE_URL`/`BELLA_LLM_MODEL`) as
its primary, explicitly-configured backend for the non-tool-calling `_build_llm_client()` — and
`.env`'s generic `VOICEAGENT_LLM_*` vars point at a real but separate backend (DeepSeek), not a
stand-in for Bella. So `_build_tool_calling_llm_client()` here checks three tiers in order:

1. Bella, via explicit kwargs (`OpenAiCompatibleToolCallingLlmClient(api_key=..., base_url=...,
   model=...)`) — matches the rest of this file's Bella-first convention — when `API_KEY` is
   set.
2. The generic `VOICEAGENT_LLM_*` vars (`OpenAiCompatibleToolCallingLlmClient()` with no args,
   which reads them itself) when only those are set.
3. `EchoToolCallingLlmClient` — the deterministic, zero-config default — when neither is set.

This is a deliberate, user-confirmed choice: support both real backends rather than picking one
arbitrarily, since both are already independently configured for other purposes in this
project's `.env`.

## Web search credentials: stub accepted for now

`BYTE_WEB_SEARCH_API_KEY` is unset in `.env`. `_build_web_search()` follows the same convention
as everywhere else in this file: real conformer (`ByteWebSearch`) when the credential is set,
else `DeterministicWebSearch`'s canned stub, with a logged warning. The user explicitly chose to
land the wiring fix now and accept the stub — `VOICEAGENT_DEMO_TOOLS=1` making tool-calling
reachable at all was the priority; a real search key is a separate, later step.

## Datetime grounding under `ToolCallingBrain`: an accepted trade-off, not a regression

`ChatBrain` (ADR-0030) grounds every turn's system prompt with the real date/time
unconditionally. `ToolCallingBrain` has no equivalent always-on mechanism — it grounds datetime
only if the model chooses to call `ClockToolSource`'s `get_current_datetime` tool for that turn.
Since `ClockToolSource` is registered in the `ToolRegistry` either way, this is accepted as an
intentional characteristic of the `VOICEAGENT_DEMO_TOOLS` opt-in path (the same limitation
ADR-0030 already reasoned about and chose not to inherit for the default path), not something
this change needs to additionally solve.

## Also fixed in passing

`ChatBrain`'s docstring cited ADR-0009's "no tool-calling conformer" claim and referenced the
wrong ADR number for its own datetime-grounding rationale (ADR-0027 instead of ADR-0030, a
pre-existing typo). Both corrected — the tool-calling conformer has existed since ADR-0029; it's
simply still not `ChatBrain`'s own path.
