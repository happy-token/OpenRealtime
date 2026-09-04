---
status: accepted
---

# Keep one production runtime and use the GPT Voice reference as a behavior specification

OpenRealtime will keep a single production runtime rooted in its existing Conversation Kernel and established Seams, while allowing substantial refactoring of that backbone. The new `server/gpt_voice_reference` coordinator is an executable behavior specification for GPT Voice-style confirmation, fast tools, background delegation, result reinjection, interruption, and session closure; it is not a second production runtime. We rejected evolving both coordinators in parallel because their overlapping session, tool, worker, and cancellation models would drift and force every integration to choose between two foundations.

## Consequences

- New behavior is implemented in the canonical runtime and validated against reference scenarios.
- Existing ADRs and Seams may be superseded when the reference exposes a better foundation; compatibility is not prioritized over a coherent core.
- RTC remains a later Transport Adapter milestone. The current foundation work focuses on low-latency interaction and tool/background-task orchestration above transport.
