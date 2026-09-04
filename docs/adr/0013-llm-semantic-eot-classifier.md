---
status: superseded
---

# Semantic EoT classifier gated at the Kernel, not inside EnergyVad/TurnPolicy

**Superseded (2026-08-10).** This file records the original post-VAD,
count-based classifier design. The `EotClassifier` Seam remains, but its
coordination and liveness rules have been replaced by the SentenceEnd + stop
dual-latch design in
[ADR-0057](0057-sentence-end-semantic-race-and-speculative-response.md) and the
effective [Semantic EoT guide](../SEMANTIC-EOT.md). In particular, the live path
no longer repeatedly classifies to consume deferral counters and no longer
fails invalid model output open to `COMPLETE`.

**Correction (2026-08-05).** This ADR's liveness claim (that
`eot_max_deferrals` bounds the wait before routing anyway) was unachievable as
coded: `EnergyVad` commits its own timer reset when it returns
`USER_EOT_CONFIRMED`, so declining that signal meant no further end-of-turn
could fire unless the user spoke again, and a user judged INCOMPLETE who then
waited for a reply waited forever. Fixed by `Vad.resume_user_utterance()` in
[ADR-0037](0037-re-armable-vad-utterances-and-client-reported-playback.md),
which also resolves the "known rough edge" this ADR recorded and deferred.

`EnergyVad` is a pure silence-timer: `_advance()` fires `USER_EOT_CONFIRMED`
unconditionally the instant `silence_duration_ms` elapses, with no hook for
anything to veto or delay that decision. `TurnPolicy` itself already
supports plugin gating for other signals — `AddresseeClassifier` and
`WakeWordDetector` both get a say before τ1 fires — but neither `EnergyVad`
nor `TurnPolicy` has an equivalent seam for EoT. Closing the semantic-
completeness gap (a transcript that reads as an unfinished thought — "I want
to" — shouldn't end the turn just because the speaker paused) meant deciding
where a new classifier consults before EoT commits.

We gated it at `ConversationKernel._handle_audio_chunk`, on the raw `Signal`
returned by the VAD, rather than teaching `EnergyVad` or `TurnPolicy` a new
hook. `EnergyVad`'s state machine is synchronous and already committed by
the time it returns a signal — `_speaking`/`_silence_ms` are reset as a side
effect of returning `USER_EOT_CONFIRMED`, regardless of what happens next.
Making `EnergyVad` support an async judge that can hold that timer open
pending a network round-trip is a real, separate change to its internals,
not a one-line addition; `TurnPolicy.evaluate()` is a sync FSM step, not a
natural place to await an LLM call either. The Kernel already sits between
the VAD and Turn Policy for exactly this kind of decision (it is where
`asr_engine` is optionally consulted before routing), so consulting an
optional `EotClassifier` there — before calling `_evaluate_and_record` at
all — reuses that seam instead of inventing a new one two layers down.

Because `EnergyVad` has already reset its own timer by the time the Kernel
decides to defer, a deferred EoT is not free of imprecision: if the speaker
resumes talking, the next loud chunk surfaces as a fresh
`USER_SPEECH_ONSET` rather than `USER_RESUMED`, since `EnergyVad` has no
memory that this is a continuation. This is harmless today — nothing is
in-flight yet at that point, so a redundant onset transition is a no-op —
but it is a known rough edge, not a promise that deferred EoT is
indistinguishable from a genuinely fresh utterance. We accepted this rather
than deferring the whole feature until `EnergyVad` grows resumption-aware
state, since fixing it doesn't change the classifier's Protocol or the
Kernel's gating point, only `EnergyVad`'s internals.

A misbehaving or misconfigured classifier must never be able to withhold a
response forever: once `EnergyVad` returns `USER_EOT_CONFIRMED`, no further
signal is guaranteed if the user stays silent. `eot_max_deferrals` (default
1) bounds how many consecutive non-`COMPLETE` verdicts the Kernel will
honor per utterance before routing anyway, and `LlmEotClassifier` itself
fails open to `COMPLETE` on any reply it can't parse — both are liveness
guarantees, not accuracy tuning.

`LlmEotClassifier` needed no new vendor or dependency: it is built entirely
on the existing `LlmClient` Protocol (`brain/llm_clients.py`), the same
seam `ChatBrain` already uses. `OpenAiCompatibleLlmClient` is already a
real conformer for it; `EchoLlmClient` works as a deterministic stand-in in
tests. No classifier is registered by default (`eot_classifier: EotClassifier
| None = None`), so unregistered behavior is byte-for-byte identical to
before this change.
