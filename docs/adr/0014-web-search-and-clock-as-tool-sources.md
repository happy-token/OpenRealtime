---
status: accepted
---

# Web Search and current-datetime as ToolSources, not Seams or a triage classifier

The research reference project ("voiceloop") bakes a respond/clock/lookup
triage into a single LLM call, backed by a real web-search vendor. Neither
half of that needed to be copied. Search-vs-not is already decided the same
way every other tool call is decided in this codebase: `ToolCallingBrain`
asks its `ToolCallingLlmClient` for a result, and a `ToolCallRequest` *is*
the decision to search. Adding a dedicated triage classifier would duplicate
what native function-calling already does, for no behavioral gain — the
same reasoning ADR-0010 already used for Knowledge Base applies unchanged:
retrieval that takes arguments in and returns text out is exactly a tool
call, not a new Seam.

`WebSearch` (`web_search/protocol.py`) is therefore modeled exactly like
`KnowledgeBase` (ADR-0010): a small, tool-agnostic retrieval Protocol
(`search(query, *, top_k=3) -> list[str]`) living in its own package,
independent of the Tool Normalization layer, plus `DeterministicWebSearch`
as its deterministic, no-network default — the "EchoLlmClient of Web
Search." `WebSearchToolSource` adapts it into one `CanonicalTool` named
`search_web`, structurally mirroring `KnowledgeBaseToolSource`.

`search_web` and `search_knowledge_base` are deliberately two separate
tools rather than one merged "search" tool. They answer different
questions with different trust and freshness properties — one is grounded
in documents this deployment explicitly registered, the other is
whatever the live web currently says — and an LLM choosing which to call
should be able to tell them apart from name and description alone, rather
than have that distinction hidden inside one tool's implementation. This
mirrors voiceloop's own reasoning for keeping `lookup` distinct from
`respond`.

`get_current_datetime` (`tools/clock_source.py`) needed no Protocol at all:
reading the local clock has no swappable backend or vendor to abstract —
it is a pure computation, not an integration point. `ClockToolSource`
still takes an injectable `now: Callable[[], datetime]` constructor
argument, but only so tests can assert on an exact timestamp; production
code never overrides it.

No real search vendor (Bing, Serper, Bocha, etc.) ships in this round.
`DeterministicWebSearch` is the only conformer, the same treatment already
given to the RTC/MQTT transports in `CONTEXT.md`'s Transport Adapter entry
— a real vendor is deferred until credentials and a vendor choice are
actually available, rather than guessed at.

One accepted limitation carries over from ADR-0009: `ToolCallingBrain`
supports exactly one tool call per turn. A single turn that needs both
"what's today's date" and a live web search cannot get both in one
round-trip — the LLM must pick one tool, get its result, and finalize.
This is the same bounded-turn shape ADR-0009 already chose over a
multi-step agentic loop, not a new gap introduced here.
