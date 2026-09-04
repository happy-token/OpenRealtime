---
status: accepted
---

# Use one Device Audio Output Runtime for playback and delivery observation

Every client renders assistant audio through one Device Audio Output Runtime behavioral boundary. It owns local decoding and resampling, the playback clock and bounded queue, output-device routing, volume, `speech_id`/Generation correlation, immediate cancel/clear, and Playback Progress measured on the negotiated audio timeline.

Device Audio Output Runtime remains separate from ADR-0070's Device Audio Input Runtime because microphone capture/prebuffer and assistant playback have different clocks, queues, failure modes, and cancellation identities. A Client Voice Session Controller coordinates both from server Voice Session Events and correlated commands without becoming authority for Session Phase, Generation, Conversation Journal, policy, or durable delivery state.

Phase 1 WebSocket playback may conform through an AudioWorklet-backed player or an enhanced AudioBufferSourceNode scheduler. A future RTC remote track is another conformer. Both must preserve the same observable contract: bounded ordered playback, stale-generation rejection, immediate queue clear, output-device lifecycle, and progress reports keyed by speech identity, audio sequence, and played samples. Transport or implementation choice cannot redefine delivered speech.

On confirmed Barge-in, the client first makes the old Generation locally ineligible and synchronously clears queued playback, then reports the last trustworthy played position. Generated, transmitted, received, queued, decoded, or scheduled audio is not treated as rendered audio. Missing or failed client acknowledgement produces estimated/uncertain delivery facts rather than a false completed record.

Output-device replacement preserves the current `output_epoch`, queue, and Speech only when the platform can switch the sink on the same AudioContext and playback clock. If replacement requires rebuilding the playback graph, the client opens a new `output_epoch`, clears the old queue, and settles the Speech as `interrupted_by_device_change`; it never migrates or replays buffers whose rendered position is uncertain. Voice Session Phase remains `ACTIVE`, input and durable Agent Tasks continue, and any later continuation is a new explicit Speech rather than silent replay.

Output ownership is scoped to a tab's Voice Session, not exclusively leased by `device_id`. Concurrent tabs may each render their own session audio; no Web Locks/BroadcastChannel takeover protocol is introduced. Each Output Runtime reports and clears only its own output epoch, Speech, and Generation.

Contract tests cover ordered gapless playback, bounded backpressure, stale chunk rejection before and after clear, cancel latency, played-position monotonicity, natural completion versus interruption, output-device replacement, AudioContext suspension, duplicate commands, reconnect, and WebSocket/RTC behavioral equivalence when an RTC conformer is later introduced.
