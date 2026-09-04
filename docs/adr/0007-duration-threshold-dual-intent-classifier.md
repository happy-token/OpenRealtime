---
status: accepted
---

# Duration-threshold DualIntentClassifier, and an opt-in-disabled SpeakingClock

**Partially superseded (2026-08-05).** This ADR's *playback-timing* section —
`SpeakingClock` as the source of how long SPEAK is held — is superseded by
[ADR-0037](0037-re-armable-vad-utterances-and-client-reported-playback.md): a
client that sends `PlaybackProgressFrame` reports real end-of-playback, and
`SpeakingClock` becomes a watchdog ceiling behind it. Its *determinism*
constraint (frame-duration ticking, never wall-clock timers) is preserved —
`PlaybackProgressFrame` is a frame, not a timer — and behavior for clients that
never report is byte-for-byte unchanged, including the `ms_per_char=0.0` default.
Two jointly-fatal bugs in the original mechanism are also fixed there: the budget
only decremented on quiet chunks in SPEAK and never in DUAL, so sustained noise
held SPEAK open forever and, since τ1 only fires from IDLE, locked the user out
entirely.

Once Turn Policy reaches DUAL and `AddresseeClassifier` has ruled out third-party speech (τ11), the system must still disambiguate τ9 (floor-claim, the assistant yields) from τ10 (backchannel, the assistant continues) for the same overlapping audio. The audio-only `AudioChunkFrame` path has no ASR transcript on it in v1 — see `conversation_kernel.py`'s own module docstring — so a content-based classifier ("嗯" vs. a full sentence) is not available. `DualIntentClassifier`'s shipped default is therefore a duration heuristic: overlap sustained past a configurable threshold reads as a floor-claim, anything shorter reads as a backchannel. This is the same class of "minimal shipped heuristic, not production-grade" default already used by `EnergyVad` and `DefaultAddresseeClassifier` — real deployments with ASR wired up should register a content-aware classifier instead.

This disambiguation is only reachable at all if SPEAK has real duration to overlap with. `ConversationKernel` previously fired `SYSTEM_EOT` synchronously right after delivering a response, so there was never a window for a concurrent `AudioChunkFrame` to be evaluated — 8 of Turn Policy's 11 transitions were unit-tested in isolation but practically unreachable through the running system. `SpeakingClock` closes that gap by estimating a playback duration from the response text and holding SPEAK open across subsequent audio chunks (ticking down using each chunk's own `sample_count/sample_rate_hz` duration, not wall-clock timers, to keep the Kernel's frame processing fully deterministic).

We made `SpeakingClock` opt-in-disabled by default (`ms_per_char=0.0`, estimating zero duration) rather than always-on, for two reasons. First, backward compatibility: the existing text-turn contract is that `SYSTEM_EOT` fires immediately after delivery, and none of the pre-existing tests should need behavioral changes to keep passing. Second, v1 has no real streaming TTS — `ResponseScheduler` delivers a response in one shot — so any nonzero estimate is already an approximation standing in for audio the system isn't actually producing yet; deployments that plug in a real TTS pipeline should size `ms_per_char` (or replace `SpeakingClock` entirely) to match their actual playback timing rather than inherit an arbitrary default.
