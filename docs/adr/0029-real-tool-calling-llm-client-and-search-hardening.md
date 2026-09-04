---
status: accepted
---

# Real ToolCallingLlmClient conformer, plus clock/search hardening

`ToolCallingLlmClient` (`brain/llm_clients.py`) had exactly one conformer:
`EchoToolCallingLlmClient`, a deterministic test stub. Its own docstring
said as much — "no tool-calling equivalent shipped yet — see ADR-0009." As
a direct result, `demos/basic_ws_server.py`'s tool-enabled path hardcoded
that stub and a throwaway `get_current_time` skill built on naive
`datetime.now(UTC)`, never touching `ClockToolSource` or
`WebSearchToolSource` at all. Asking the live agent about the time or a
live web fact therefore never went through a real model choosing and
using a real tool — it either got a guessed answer or nothing. This is
the gap this ADR closes, informed by how the sibling project
the sibling reference project handles the same two questions.

## OpenAiCompatibleToolCallingLlmClient

`brain/plugins/openai_compatible_tool_calling_llm_client.py` mirrors
`OpenAiCompatibleLlmClient`'s conventions (same
`VOICEAGENT_LLM_API_KEY`/`_BASE_URL`/`_MODEL` env vars, same
sync-request-in-a-thread pattern) but speaks the OpenAI-compatible
function-calling shape: each `CanonicalTool` becomes a
`{"type": "function", "function": {name, description, parameters}}`
entry, and a reply is parsed into either a `ToolCallRequest`
(`choices[0].message.tool_calls[0]`) or `FinalText` (`.content`). If a
model returns more than one tool call on the first turn, the client uses
the first and logs a warning rather than raising — the single-call
contract is this codebase's assumption, not something an external model
response can be trusted to honor, so a violation is degraded gracefully
instead of crashing the turn. A second tool call arriving on the
`tool_result` follow-up call, however, is impossible to degrade
gracefully (ADR-0009's brain has nowhere to route it). A live smoke test
against a real DeepSeek endpoint (DeepSeek's `/chat/completions` is
OpenAI-compatible) hit this directly: given an uninformative tool result
("No results found." — `DeterministicWebSearch`'s honest answer for an
unregistered query), the model tried to call `search_web` again instead
of finalizing, and the client crashed the turn. The fix is to simply not
offer `tools` on the follow-up request — the model can't ask for a
second call if none are on offer. `_parse_response`'s `RuntimeError` for
a second tool call on `second_call=True` stays in as a defensive
backstop for a provider that returns `tool_calls` unprompted, not the
expected path.

The harder problem is the second `complete()` call. Sending a tool
result back to an OpenAI-compatible endpoint requires replaying the
assistant's original tool-call message plus a `role: "tool"` message
carrying the result and matching `tool_call_id` — but
`ToolCallingBrain.respond()` (`brain/tool_calling_brain.py`) never passes
the original tool name/arguments back on that second call, only the
result text. The client therefore stashes the pending tool call
(synthetic id, name, arguments) on `self` between the two `complete()`
calls of one turn, and asserts if a `tool_result` arrives with nothing
stashed. This is safe specifically because of how this codebase builds
and drives brains: `_build_kernel` constructs one brain (and therefore
one client) per connection, and `server/cli/harness.py` awaits each
connection's turns sequentially — there is never a second turn's first
call interleaved with a first turn's second call on the same instance.
A design that assumed concurrent or reentrant turns on one client
instance would not get to make this simplification.

## Clock hardening

`ClockToolSource` (`tools/clock_source.py`) previously returned whatever
`datetime.now()` produced, un-timezoned — the model had to guess what
"now" meant for the user, exactly the kind of guesswork this project's
Canonical Tool pattern exists to avoid. It now resolves an explicit IANA
timezone (`VOICEAGENT_CLOCK_TIMEZONE`, default `Asia/Shanghai`, matching
realtime's precedent) via stdlib `zoneinfo`, and returns an ISO 8601
timestamp with UTC offset plus the weekday name, so a model never has to
compute date/weekday arithmetic itself. It stays a zero-argument tool —
realtime's "IANA tz|day-offset" query mini-language is coupled to
realtime's own combined-brain protocol, which this project is not
adopting (ADR-0014 already made that call for the tool's shape; this
only changes what a call returns).

## Search hardening, and reconciling ADR-0016

ADR-0016 argued `ByteWebSearch` didn't need SSRF-style URL filtering
because "a `WebSearch` result is inert text handed straight to an LLM as
a tool result... there is no consumer-side risk on OpenRealtime's end for
that filtering to protect against." That reasoning was about *fetch*
risk — OpenRealtime's own server never dereferences a result URL — and it
is still correct on those terms: this change does not make OpenRealtime
fetch anything it didn't before.

The filtering added here answers a narrower, different question:
whether a URL is fit to *display* as a citation at all. A malformed or
adversarial vendor response could point a "citation" at
`http://169.254.169.254/...` or embed credentials in a URL a user might
be told to visit — harms that land on whoever acts on the spoken/text
reply, not on OpenRealtime's own request path. `_is_safe_public_url`
(`web_search/plugins/byte_web_search.py`) therefore rejects non-http(s)
schemes, embedded credentials, and any IP-literal hostname in a
private/loopback/link-local/reserved/unspecified/multicast range, before
a result is turned into a passage. Deliberately, it does not resolve
domain-name hostnames via DNS to check the address they resolve to —
unlike realtime's `normalize_result_url`, which fetches results and so
has a real SSRF surface to close. Adding a live DNS lookup to a pure
validation step here would make it flaky (this was caught directly: an
early version did resolve hostnames, and it dropped a well-formed test
result whose fake domain didn't resolve) without closing any request
that OpenRealtime was ever going to make. ADR-0016's "left out rather than
carried over speculatively" framing was about not preemptively copying
realtime's SSRF logic; this ADR is the point where a concrete,
OpenRealtime-shaped reason to add a piece of it (citation-safety, not
fetch-safety) actually materialized.

Response reads are also now bounded (`_read_bounded_json`, capped at 1MB
in 64KB chunks) rather than a single unbounded `.read()`, so a
misbehaving or malicious upstream can't force this process to buffer an
arbitrarily large response. Each surfaced passage now carries its source
host and a `retrieved_at` timestamp, so a downstream answer can be
presented as time-qualified rather than a timeless fact —
`WebSearchToolSource` needed no code change for this, since it already
passes `ByteWebSearch`'s returned strings straight through.

## What stayed out of scope

Realtime's combined-brain and speculative-lookup-coordinator
(`fillers/combined_client.py`, `fillers/lookup_coordinator.py`) were not
ported. That machinery exists to hide search/tool latency behind
speculative filler audio in realtime's own architecture, and ADR-0009
already rejected a multi-step/looping tool-calling brain for this
project in favor of one bounded round trip. This ADR only makes that one
round trip actually work end-to-end with real conformers; it does not
revisit ADR-0009's bounded-turn shape.
