---
status: proposed
amends: [0065]
---

# Versioned provider-bridge admission and host-owned latency

OpenRealtime will keep the existing typed ASR, Brain, and TTS capability seams as the runtime contract for provider bridges. A user-submitted bridge may be represented by a versioned Plugin Manifest only when its placement is sidecar or remote; it cannot be imported into the Web or voice process. A manifest claim is insufficient for activation: the bridge must pass observable contract probes in an isolated environment.

The realtime admission contract is deliberately stricter than the legacy adapter interfaces. ASR must produce partial and final text for a test turn. TTS must emit audio before a multi-chunk text stream is committed, using one duplex session. LLM must emit ordered, incremental text. Commit-only TTS and batch-only ASR may remain available to non-realtime use cases, but cannot be selected for a realtime conversation. A contract failure is explicit; it never triggers an unannounced provider substitution.

The host measures four spans using one monotonic clock: first ASR audio frame to first non-empty text, last ASR audio frame to final text, first TTS text chunk to first non-empty audio, and LLM request dispatch to first non-empty text. Empty chunks, heartbeats, tool-only responses, timeouts, and cancellation do not manufacture a successful first-event duration. Vendor timings are supplemental diagnostics, not the authoritative span. The host reports the instance and immutable bridge version with each span but never raw audio, transcript, prompt, or credentials.

The first implementation steps add manifest admission and sequence probes, a provider-neutral timing trace, and host-owned ASR/TTS timing wrappers on the current cascaded session path. The OpenAI-compatible streaming LLM client records its own dispatch-to-first-text span at the actual request boundary. Additive migrations introduce personal and platform built-in provider instances and explicit selections; admission pins the selected instance and configuration revision while preserving the legacy key fallback when no instance is selected. Timing records include that identity when available. These pieces do not execute user code, constitute full realtime capability tests, or cover every existing LLM path. The next step must connect the probes to an isolated sidecar protocol and prove containment before the UI allows a user bridge to become active. Existing environment and per-provider credentials remain a compatibility path, not an implicit replacement for an explicit choice.
