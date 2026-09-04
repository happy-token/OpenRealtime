---
status: accepted
---

# Re-armable VAD utterances, and client-reported playback progress

**Superseded in part (2026-08-09).** The re-arm contract remains active, but
the semantic path is no longer only a post-hoc acoustic veto and `AsrSession`
now exposes revisioned partial/final state. See
[ADR-0057](0057-sentence-end-semantic-race-and-speculative-response.md).

Two defects from the 2026-08-05 review ([docs/ASSESSMENT.md](../ASSESSMENT.md)),
both traceable to the same root cause: the Kernel made turn-taking decisions on
state it did not actually own — the VAD's silence timer, and the assistant's
real playback position. Companion to
[ADR-0036](0036-concurrent-turn-execution-and-real-barge-in-cancellation.md).

## `Vad.resume_user_utterance()`

`_OnsetEotTracker.advance` commits `_speaking = False; _silence_ms = 0` as a
*side effect* of returning `USER_EOT_CONFIRMED`. Two Kernel paths decline that
signal, and neither could recover from it:

- **A deferred semantic end-of-turn.** `_should_defer_eot` returning True made
  `_handle_audio_chunk` return early. Every subsequent quiet chunk then hit
  `if not self._speaking: return None`, so no further `USER_EOT_CONFIRMED`
  could ever fire. **A user judged INCOMPLETE who then simply waited for a
  reply waited forever** — the turn was silently lost, on the primary
  semantic-completeness path.
- **A confirmed barge-in.** τ9 lands in LISTEN, but SPEAK/DUAL only ever call
  `measure_chunk`, so the tracker still believed the user was not speaking. The
  interrupting utterance could never reach an end-of-turn, and the transcript
  ADR-0015 deliberately left buffered for the ordinary LISTEN path could never
  be claimed.

The `Vad` Protocol gains `resume_user_utterance()`, implemented on the shared
`_OnsetEotTracker` and delegated by both `EnergyVad` and `SileroVad`. It grants
the utterance a *fresh* `silence_duration_ms` window rather than restoring the
elapsed silence, so the next end-of-turn is a genuine new timeout instead of
re-firing on the very next quiet chunk. It also clears `_hesitated`: on the
barge-in path the tracker was never advanced during SPEAK/DUAL, so a stale
`True` would make the next loud chunk emit `USER_RESUMED` instead of continuing
the utterance silently.

Liveness is now bounded and requires no further speech from the user: each
re-arm costs one more silence window, and `_should_defer_eot` caps honored
deferrals at `eot_max_deferrals + eot_uncertain_max_deferrals`, after which the
turn routes.

**Correction to [ADR-0013](0013-llm-semantic-eot-classifier.md) (2026-08-05).**
Its ¶4 liveness claim — that `eot_max_deferrals` bounds the wait "before routing
anyway" — was unachievable as coded, and its own ¶3 admits "no further signal is
guaranteed if the user stays silent" without noticing that this voids ¶4.
[ADR-0021](0021-eot-dual-scorer-ensemble-and-split-liveness-bound.md) inherited
the same problem: it describes the cap as "how many more silence-timeout cycles
to tolerate," presupposing cycles the code could not produce. Both are now true
for the first time.

One deviation to record: ADR-0013 ¶3 pre-authorized this fix as touching "only
`EnergyVad`'s internals," and ADR-0021 declined it as "a real change to its
internals, not a one-line addition." It is in fact both — the internals change
*and* the `Vad` Protocol widens by one method. That is deliberate rather than
duck-typed via `getattr`: Kernel liveness now depends on the method existing, so
it should be a checkable contract. (Nothing currently checks it —
[ISSUE-0024](../ISSUES.md#issue-0024-no-ci-and-pytyped-promises-what-nothing-verifies).)

## Client-reported playback progress

`SpeakingClock.estimate_ms` is `len(text) * ms_per_char`, explicitly decoupled
from real synthesis, and the live demo used `ms_per_char=180.0` — roughly 3×
too long for English text, which `EchoLlmClient` emits. Turn-taking decisions
were being made on a fiction.

Worse, `_speaking_ms_remaining` was decremented **only on quiet chunks in
SPEAK, and never in DUAL**. Sustained audio above the energy threshold meant the
budget never drained, `SYSTEM_EOT` never fired, and the FSM ping-ponged
SPEAK ↔ DUAL. Because τ1 only has a rule from IDLE, **a noisy room locked the
user out of ever starting another turn.**

Three changes:

**The budget ticks on every chunk, in both SPEAK and DUAL.** Wall-clock time
passes whether or not the user is making noise. `_tick_speaking_budget` is the
one place this happens, and it respects ADR-0036's `_awaiting_playback` gate.

**An exhausted budget in DUAL resolves the overlap.** `_TABLE` has no
`(DUAL, SYSTEM_EOT)` rule, so a correct decrement alone still could not leave
DUAL. Rather than add a twelfth transition, an exhausted budget routes through
the existing τ9/τ10/τ11 classification: τ9 → LISTEN with a re-armed VAD, so the
noise ends in a normal end-of-turn; τ10/τ11 → SPEAK with a spent budget, so the
next chunk fires `SYSTEM_EOT` → IDLE. Every branch leaves DUAL, and
[docs/full-duplex-survey.md](../full-duplex-survey.md)'s canonical
eleven-transition table is not extended.

**A new inbound `PlaybackProgressFrame(generation, finished)`** lets the client
report real end-of-playback from its audio source's `ended` event, which the
Kernel treats as authoritative: `SYSTEM_EOT` in SPEAK, or resolve the overlap in
DUAL (which is what lets a web client leave DUAL without waiting for another
audio chunk to notice the budget is spent). Stale or forged generations are
rejected — inbound frames are untrusted like any other.

`SpeakingClock` is **not** switched off in reported mode; it becomes a watchdog
ceiling (`max(estimate × 3, 30s)`). A client that reports once and then goes
away — backgrounded tab, socket dropped mid-playback, an `ended` event that
never fires — would otherwise hold SPEAK forever, trading one liveness hole for
another. One field, two roles, no second state machine.

The client only ever reports from a genuine `ended` handler, never from
`armFallback`'s 1200ms timer, which would opt a no-audio demo
(`SilentTtsEngine`) into reported mode on a fabricated timestamp.

**Supersedes the playback-timing section of
[ADR-0007](0007-duration-threshold-dual-intent-classifier.md).** Its
determinism constraint is preserved and was a real design pressure here:
`PlaybackProgressFrame` is a *frame*, not a wall-clock timer, so the Kernel's
frame processing stays deterministic. And behavior for clients that never report
is byte-for-byte unchanged, including the `ms_per_char=0.0` default under which
`SYSTEM_EOT` still fires immediately after delivery exactly as in v1.

## What this does not fix

Hesitation handling is still acoustic, not semantic:
`hesitation_silence_ms` is a shorter silence threshold, so utterance *content*
remains irrelevant to whether WAIT is visited. And the `EotClassifier` remains a
post-hoc veto downstream of an acoustic decision, because `AsrSession` exposes
no partial/interim hypothesis interface — `speech/asr.py` states it as an axiom
("an AsrEngine only answers 'what did they say,' never 'are they done
talking'"), which is what forecloses ASR-stability, prosodic, and speculative
approaches. See [docs/INTERACTION-CASES.md](../INTERACTION-CASES.md) cell 6 and
[docs/LATENCY.md](../LATENCY.md).

There is also still no wall-clock escape from SPEAK/DUAL if a client stops
sending audio *and* never reports playback. `PlaybackProgressFrame` covers web
clients and an always-on mic covers the rest; a timer would contradict ADR-0007's
determinism rule and needs its own ADR.

## Testing

Each defect has a test that fails when its fix is reverted, asserting an
outcome rather than a transition list:
`test_deferred_eot_is_answered_from_continued_silence_with_no_further_user_speech`
(deliberately supplies no second loud chunk — which is exactly what every
pre-existing deferral test did supply, and why none of them caught this),
`test_sustained_loud_noise_during_speak_does_not_trap_the_kernel_in_dual`, and
`test_a_new_user_turn_is_still_answered_after_sustained_noise_during_speak`.

Two pre-existing `dual_self_loop` tests needed their fixture clock raised: at
50ms/char their 600ms budget is now spent before the 3100ms of overlap they
script, and they had been implicitly relying on the DUAL budget never ticking —
i.e. on this bug. Their intent (the self-loop) is preserved.

Three `EotClassifier` deferral tests changed from `generation=2` to
`generation=1`: a deferred continuation is no longer a fresh
`USER_SPEECH_ONSET`, so one utterance now correctly carries one generation.
That is ADR-0013 ¶3's "known rough edge" being resolved.

Verified against the real transport as well: a scripted WebSocket client sent 6
seconds of continuous noise during the assistant's turn and then took a fresh
spoken turn, which was answered.
