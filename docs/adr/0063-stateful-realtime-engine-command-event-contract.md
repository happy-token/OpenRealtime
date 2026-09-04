---
status: accepted
---

# Stateful Realtime Engine with one command/event contract

OpenRealtime replaces the turn-scoped `ConversationEngine.respond()` target with a stateful `RealtimeEngine.open() -> RealtimeConversation` boundary. A Realtime Conversation accepts explicit, correlated `RealtimeCommand`s and emits one ordered `RealtimeEvent` stream for its whole lifetime. The same contract supports a Native Realtime Engine backed by an end-to-end speech model and a Cascaded Realtime Engine composed from VAD, ASR, Turn Manager, Brain, Speech Renderer, and TTS. Brain belongs inside the Engine boundary; only the Cascaded form exposes its internal capabilities as replaceable seams. In Cascaded mode, Turn Manager is the sole authority for Dialogue State, EoT, turn admission, and floor arbitration; VAD, ASR, playback, and semantic classifiers supply evidence only.

Application Control Plane remains the authority for Journal commits, tool policy, confirmation, and Agent delegation. Commands with authoritative side effects are mediated there before the Engine implementation sees a committed projection or correlated result; a Native provider adapter never writes canonical history or grants itself execution authority.

This decision supersedes the public target interface in ADR-0041, ADR-0047, and ADR-0048 while retaining their provider-neutral streaming, cancellation, correlation, and Control Plane principles. `VoiceEvent`, `ConversationAction`, and `ConversationEngine.respond()` remain migration-only types behind a compatibility adapter. Native and Cascaded implementations are compatible only after passing the same Realtime Engine Contract Suite; matching method signatures is insufficient.

Phase 1 production scope is Cascaded-only. The existing Native implementation and its deterministic contract tests are retained as frozen experimental code, but it is not production-registered, configured, integrated with real credentials, or included in release/SLO gates. It cannot delay Cascaded or Voice Session Runtime changes; future production use requires a separately scheduled conformance and live-service effort.

We rejected keeping a turn-only interface because it cannot safely express asynchronous `AppendItem`, Agent-result injection, external speech text, configuration updates, tool results, playback progress, or session-wide cancellation. We also rejected exposing separate public protocols for Native and Cascaded engines because Application Control Plane and clients would then depend on provider topology.
