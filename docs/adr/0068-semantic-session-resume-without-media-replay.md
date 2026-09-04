---
status: accepted
---

# Resume Voice Sessions from semantic state, never buffered media

Voice Session Runtime replaces ADR-0019's raw `OutboundFrame` buffering with Semantic Session Resume. A reconnect presents its authorized session identity and last applied session, Journal, and playback positions; the Runtime restores a bounded event tail or emits a Voice Session Snapshot, re-establishes Engine and client readiness, and only then returns the session to `ACTIVE`.

Audio deltas, partial transcript deltas, and other stale presentation frames are never replayed. Speech active at disconnect is settled as interrupted or uncertain, while committed Conversation Items, lifecycle facts, work state, and delivery facts are reconstructed from their authorities; Endpoint attach/detach and a bounded grace period remain valid, but physical reconnection alone never proves semantic recovery.

ADR-0070's Device Audio Input Runtime prebuffer is not an exception to this rule. It may retain only newly captured microphone PCM inside the current client `input_epoch` while `STARTING` or `RECONNECTING`, and may release it only after the matching server barrier succeeds. Disconnect/session replacement resets the old epoch; stale output, network frames, and prior-epoch microphone audio are never replayed. Overflow invalidates the buffered utterance rather than emitting a truncated tail.

Semantic Session Resume is limited to a still-live Runtime within its grace period. After process loss, deployment restart, or grace expiry, the old Voice Session is terminal and the client creates a new `voice_session_id` linked by `previous_voice_session_id` to the same persistent `thread_id`; Conversation Journal, Agent Task Store, and delivery authorities restore continuity without claiming that the previous live media session survived.

Whenever recovery opens or replaces a Realtime Conversation, a Model Context Restoration Barrier captures the authoritative Journal target sequence, applies speech-delivery-aware projection in order, and forbids `ACTIVE` or a new model response until the Engine confirms visibility through that target. A transport reconnect that preserves the same healthy Engine does not duplicate history, but must still prove the Engine's projected sequence before recovery completes.

Recovery completion is one server-authoritative barrier, not a collection of independently visible successes. Against one frozen recovery target, the Runtime validates identity/session/cursors; restores Journal and model context; rebuilds Agent Task, Tool, and Pending Confirmation projections from their authorities; settles playback and delivery facts; and establishes a gap-free Snapshot/event-tail sequence boundary. The client may render reconnecting state while this runs, but ordinary input is not admitted to Turn or Engine and no response may be requested.

A required barrier failure leaves the session in `RECONNECTING` with a structured, retryable or terminal reason. Crossing the recovery deadline settles the old session through `STOPPING → CLOSED` and returns a continuation-required outcome. Continuity then uses a new `voice_session_id`, the same `thread_id`, and `previous_voice_session_id`; partial recovery never masquerades as a successful resume.

Phase 1 keeps the active Voice Session Registry, Snapshot cache, and bounded `session_sequence` event tail only in the owner process. Same-session resume therefore requires grace-bounded sticky routing to that process. Snapshot is rebuilt from live state and the Journal/Task/Confirmation/Delivery authorities rather than persisted as another authority; lifecycle boundaries may be journaled and detailed runtime events may enter Event Ledger for audit, but neither ledger replay nor a database row resurrects execution.

Process loss, deployment restart, unreachable ownership, or grace expiry creates a Voice Session Continuation instead of restoring the same live identity. Phase 1 introduces no Redis Session directory. A future external directory requires a separate scale/availability decision and still cannot become semantic history, task, confirmation, or delivery authority.

Accordingly, Phase 1 deploys `/voice/ws` to one Voice Runtime process rather than multiple workers with isolated registries. Other HTTP/UI services may scale separately. The Voice process supports bounded concurrent sessions but has no live-session hot failover; health-managed restart plus semantic Continuation is the declared recovery behavior until measured capacity requires consistent session routing or an external directory.

Reconnect resource retention has two levels. Detach immediately stops input admission, cancels/settles the active Response, Speech, Fast Tool Loop, and playback facts. For the first 5 seconds, the Runtime keeps the Cascaded Conversation, provider connections, and realtime capacity as a fast-resume window. It then quiesces ASR/TTS/audio queues and releases realtime admission resources while retaining only lightweight session/event-tail/snapshot metadata until the total 60-second grace expires.

A reconnect during the quiesced interval reuses `voice_session_id` only after reacquiring Admission, rebuilding the Cascaded Conversation, and passing Model Context Restoration Barrier. Temporary saturation leaves it `RECONNECTING` with `retry_after`; grace expiry closes it and requires Continuation. Durable Agent Tasks and background Context Compressor work are not cancelled by realtime quiescence.

Same-session resume is also gated by ADR-0072 authentication and token proof. A raw `voice_session_id` never authorizes attach: the detached Registry entry, hashed rotating Resume Token, authenticated endpoint identity, protocol version, and grace must all match before Recovery Barrier begins.
