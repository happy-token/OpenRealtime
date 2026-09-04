---
status: accepted
date: 2026-08-10
---

# Speculatively ground each chat turn with frozen time and typed web evidence

## Context

The default Voice Web Demo used `ChatBrain`, not the opt-in `ToolCallingBrain`.
It injected one local timestamp on every turn, but could not represent a target
timezone plus relative calendar date. Web search existed only behind the demo
tools flag and returned flattened strings with no stable trust or failure
contract. Consequently the ordinary low-latency voice path could not verify
weather, news, markets, or other current facts.

VoiceLoop's `datetime-and-web-search.md` and current source demonstrate useful
portable behavior: decide respond/clock/lookup, freeze the wall clock once,
apply relative dates in the target timezone, start read-only lookup from a
SentenceEnd candidate, reuse it after semantic acceptance, and inject search
results as explicitly untrusted evidence. Its `CombinedBrainClient` ownership
model and lack of a Tool Registry do not match OpenRealtime's architecture.

## Decision

1. Add a small `TurnGrounder.resolve(transcript) -> TurnGrounding` seam in the
   Brain layer. `RealtimeGroundingCoordinator` hides planning, clock
   calculation, provider calls, deadlines, and failure degradation.
2. Add `GroundingPlanner` with an `LlmGroundingPlanner` conformer. It returns a
   strict one-object JSON plan for `respond`, `clock`, or `lookup`, including a
   self-contained bounded query and an explicit no-network decision. It prefers
   the cancellable `StreamingLlmClient` path so a planning deadline closes the
   provider stream instead of merely abandoning a background completion.
3. Freeze one timezone-aware instant per resolution. Clock selectors are
   `<IANA timezone>|<-7..7>`; relative dates are calendar-day operations after
   converting to the target timezone, not fixed 24-hour duration arithmetic.
4. Deepen the existing `WebSearch` contract to return immutable
   `LookupEvidence(SearchResult...)` and normalize provider failures into a
   stable vocabulary. Evidence is marked `untrusted`, bounded before model
   projection, and never inserted as authoritative system instructions.
5. In the default live ChatBrain path, build the Grounder whenever real LLM
   credentials exist. Enable real lookup only when
   `BYTE_WEB_SEARCH_API_KEY` exists; the deprecated VoiceLoop name
   `WEB_SEARCH_API_KEY` is accepted as a migration alias, with the canonical
   name taking precedence. A deterministic test double is never advertised as
   a live search provider.
6. Keep the canonical Tool Registry and policy path. `ClockToolSource` and
   `WebSearchToolSource` reuse the hardened clock/search modules when tool mode
   is explicitly enabled; the Grounder does not become a generic side-effect
   executor.
7. Rely on the existing `SpeculativeStreamingBrain` lifecycle: the Grounder
   begins inside the one response producer at SentenceEnd, stable commit reuses
   it, and activity invalidation cancels it. No duplicate task is spawned for
   the same generation and transcript revision.
8. Bound planner, search, and total Grounder duration to 1.5s, 3s, and 5s by
   default. A failure produces safe model context rather than guessed current
   facts.

## Consequences

- Ordinary live voice turns can answer clock questions without network access
  and can use real search without switching to the non-speculative tool mode.
- Search latency overlaps semantic endpoint acceptance, while the main reply
  remains an SSE stream into incremental TTS.
- One small planning LLM request precedes the main reply on credentialed
  ChatBrain turns. This is a measurable latency/cost tradeoff; combining it
  with semantic EOT is deferred until traces show that an additional seam
  would preserve both contracts cleanly.
- Web providers can be replaced without changing ChatBrain, and planners can be
  replaced without changing date/search adapters.
- Search acknowledgment events, HTTP connection pooling, Journal history
  projection, and migration of VoiceLoop's semantic evaluation corpus remain
  follow-up work. They are documented explicitly rather than hidden behind a
  claim of full parity.

This decision claims alignment with the documented target behavior, not
knowledge of private GPT Voice internals.
