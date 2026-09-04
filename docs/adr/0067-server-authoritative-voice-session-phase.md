---
status: accepted
---

# Make Voice Session Phase server-authoritative

Voice Session Runtime owns an explicit `INACTIVE → STARTING → ACTIVE → RECONNECTING → STOPPING → CLOSED` lifecycle that is independent of Dialogue State and physical transport connection state. `ACTIVE` is reached only after Endpoint hello/resume, Realtime Profile resolution and conversation opening, controller/event-pump startup, and client audio readiness have all passed; reconnect preserves `voice_session_id` and `thread_id`, while startup failure or recovery timeout settles through `STOPPING → CLOSED`.

Returning from `RECONNECTING` to `ACTIVE` additionally requires the atomic Recovery Barrier defined by ADR-0068: authorized cursor validation, Journal/model-context restoration, work and confirmation reconstruction, playback/delivery settlement, and a gap-free Snapshot/event-tail boundary. Completing only some of these conditions does not admit ordinary input or generation.

Voice Session identity is not exclusive per device or browser profile. Concurrent tabs use independent `voice_session_id`, media epochs, Generation, Phase, and cancellation scopes. They normally open separate Threads; explicitly opening the same conversation may bind multiple Voice Sessions to one `thread_id` without allowing one Session's Barge-in or media command to affect another.

Voice Session Admission is another mandatory `STARTING → ACTIVE` barrier and precedes release of device prebuffer. It reserves capacity against live sessions, event-loop lag, memory/audio queues, and ASR/TTS provider limits. Saturation returns structured `capacity_exhausted` plus `retry_after` and accepts no ordinary audio; an active session is not evicted for a newcomer. Background compression, Agent notifications, and optional analysis have separate lower-priority budgets. Per-tenant/user abuse quotas are allowed, but `device_id` is not an exclusive lease and legitimate concurrent tabs remain supported.

`STOPPING` is a bounded settlement phase, not an immediate socket close. It stops input and clears device media; advances Generation and cancels Response/Speech/Brain/TTS/Fast Tool work; settles delivery from the last trustworthy playback position; invalidates session-bound pending confirmations while leaving durable Agent Tasks alive; records Journal/Outbox terminal facts; then closes pumps, Conversation, capability sessions, Endpoint, Admission, and Registry state before emitting `CLOSED`. Missing playback becomes uncertain and cleanup timeout becomes a named degraded-close outcome, never false success.

An ordinary session has a 5-second close deadline. Process termination permits at most 15 seconds to drain all Voice Sessions; after that, remaining external operations are cancelled or recorded as indeterminate and process exit is not blocked indefinitely.

Lifecycle failures use one versioned Voice Session Failure envelope: diagnostic `error_id`, stable `code`, current Phase, retryable flag, optional retry delay, session disposition (`keep_reconnecting`, `close`, or `continuation_required`), and safe message. The initial codes distinguish authentication, protocol incompatibility, capacity, invalid command, provider availability, context restoration, recovery deadline, continuation, and internal failure. Clients never parse prose for control flow, and provider/stack/credential/resource-existence details remain server-side behind `error_id`.

The Runtime reports this lifecycle through a distinct `VoiceSessionEvent` family rather than extending `RealtimeEvent`, because a Voice Session exists before, between, and after replaceable Realtime Conversations. Both event families may be multiplexed over one client control channel, but Voice Session Events carry their own server-assigned `session_sequence` and remain runtime-owned.
