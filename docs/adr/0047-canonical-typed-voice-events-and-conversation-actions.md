---
status: superseded by ADR-0063
---

# Use typed Voice Events and Conversation Actions as the internal protocol

All external stimuli are normalized into versioned, strongly typed Voice Events before Conversation Kernel sees them, and the Kernel coordinates work through vendor-neutral Conversation Actions. This follows GPT Voice's observable event-driven Realtime, Sideband, tool, and delegated-thread behavior while preventing OpenAI, Doubao, WebSocket, or future RTC payloads from leaking into the production core. We rejected stringly typed dictionaries and direct provider callbacks because they make ordering, replay, compatibility, and replacement behavior implicit.

## Consequences

- Every Voice Event carries Interaction Context, `event_id`, per-Voice-Session sequence, timestamp, and schema version.
- Boundary adapters own wire parsing and provider-to-canonical translation; Transport Frames remain boundary types.
- Voice Event and Conversation Action are closed, typed unions with explicit unknown-version handling.
- Conversation Kernel is the ordering authority for one Voice Session.
- Event Ledger observes accepted facts for audit and metrics but cannot mutate decisions or serve as an implicit message bus.
