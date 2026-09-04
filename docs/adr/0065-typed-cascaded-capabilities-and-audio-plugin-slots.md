---
status: accepted
---

# Typed Cascaded capabilities and audio-plugin slots

A Cascaded Realtime Engine composes session-scoped asynchronous VAD, ASR, Turn Manager, Brain, Speech Renderer, and TTS capabilities. Stateful capabilities accept typed commands and emit typed events; they never call each other directly. The Engine owns routing, ordering, bounded backpressure, cancellation, and lifecycle. Audio uses negotiated, timestamped Audio Frames on a shared Audio Graph rather than a fixed PCM16/16 kHz/32 ms contract.

Additional audio extensions use three typed slots: Audio Processor Plugins transform frames in an ordered chain; Audio Analyzer Plugins observe frames and emit non-authoritative evidence such as Speaker Evidence; Audio Sink Plugins store, forward, or monitor without participating in decisions. Plugins declare a versioned Manifest, capabilities, placement, data access, latency budget, and explicit failure policy. Data Grants and a minimized Capability Context constrain exposure; a Realtime Profile may reduce but never expand approved grants. v1 provides Python in-process bindings, while Capability Bridges preserve the same logical contract for later sidecar and remote implementations.

Device Capture Profile metadata participates in Audio Graph negotiation. A Processor for AEC, noise suppression, or gain is admitted only when that effect is not already reported effective on the device, so one media path never applies the same effect twice. Phase 1 WebSocket profiles do not admit server AEC because they lack a sufficiently aligned playback-reference side input; absence is explicit rather than simulated by a no-op Processor.

Realtime Profiles are validated into immutable Resolved Realtime Profiles before media starts. Required capabilities must be satisfied; preferred capabilities may degrade only with explicit events. Silent fallback, unlimited queues, critical-path silent frame loss, and in-place provider hot-swap are forbidden. Replacing a stateful implementation requires a Realtime Reconfiguration Barrier and Journal-based context rebuild. Every Engine and plugin binding must pass its applicable behavioral Contract Suite.

We rejected a universal plugin callback because processors, analyzers, sinks, and turn authorities have different mutation rights, latency effects, and security consequences. We also rejected baking current packet size or Python import paths into the public contract because both would prevent portable user-provided implementations.
