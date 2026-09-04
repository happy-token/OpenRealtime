---
status: accepted
---

# Concurrent turn execution, and barge-in that actually cancels

The 2026-08-05 review ([docs/ASSESSMENT.md](../ASSESSMENT.md)) found the
framework was full-duplex on paper and half-duplex at runtime, and that
barge-in walked the right transitions while cancelling nothing. Both are fixed
here. Both were invisible to a fully green 425-test suite, for reasons recorded
in [ISSUE-0021](../ISSUES.md#issue-0021-the-test-suite-asserts-fsm-traversal-not-interaction-outcomes).

## Concurrent turn execution

`ConversationKernel.run` was `async for frame in transport.receive(): await
self._handle_frame(frame)` — a single sequential loop. One frame's entire
pipeline, including `router.decide()` (up to the LLM client's 15s default
timeout) and `response_scheduler.deliver()` (which for
`StreamingSpokenResponseScheduler` streams *every* TTS chunk), had to finish
before the next inbound frame was read off the transport iterator.

So no audio was read for the whole think-and-speak window, and Turn Policy's
τ8–τ11 overlap family was unreachable with any real vendor in the loop. It was
demonstrable only under the zero-latency test defaults, which is exactly what
the acid-test bench used.

`_spawn_turn` now runs each committed turn's Brain call and delivery in its own
tracked `asyncio.Task`, so the frame loop returns to reading immediately. This
is the minimal cut: `_route_and_respond` is the only awaited region longer than
a few milliseconds, and everything it touches was already designed to be
lease-gated.

**Turn tasks are never cancelled.** Supersession is by Generation advance only.
Cancelling would risk tearing down a coroutine suspended inside `websockets`'
`send`, which can leave the connection unusable — and the correctness argument
was already settled by
[ADR-0008](0008-status-inquiry-classifier-and-single-inflight-delegation.md):
"cancellation-by-supersession here is a promptness optimization, not the
correctness mechanism — the Generation-lease check is what actually prevents a
stale result from being spoken."

> **Amendment — ADR-0048:** the Generation lease remains the correctness
> boundary, but the target streaming architecture now also propagates cooperative
> cancellation into Conversation Engine, provider generation, and TTS producers.
> Transport delivery stays lease-guarded, so a cancellation-hostile dependency or
> late external delta is still observationally inert. The never-cancel rule above
> describes the legacy whole-turn implementation, not the accepted target contract.

That gives the invariant this change rests on:

> **Invariant T.** At most one live turn task holds a current
> `GenerationLease`. Any other live turn task has a stale lease, and every
> state mutation it can perform is lease-guarded, so it is *observationally
> inert* — it can consume CPU and vendor quota, never affect Turn Policy, the
> transport, or the speaking budget.

Two pieces of state had to be brought under that guard, because concurrency
newly exposed them:

- **The speaking budget.** `_begin_speaking` is now the single writer of
  `_speaking_ms_remaining` and the only place a delivered response drives Turn
  Policy, and it re-checks the lease first. Without that, a barge-in landing
  between `deliver()` returning and the budget being installed would let a dead
  turn install a fresh speaking window or fire `SYSTEM_EOT`.
- **The awaiting-playback gate.** Turn Policy enters SPEAK at the RESPOND
  transition, *before* the Brain has been called, and the budget is `0.0` at
  that moment. Once the frame loop stopped blocking, the first quiet chunk
  would spend a zero budget and fire `SYSTEM_EOT` while the Brain was still
  deciding — killing every turn. `_awaiting_playback` suppresses budget ticking
  in that window while leaving overlap *detection* live, since barge-in during
  think-time is a real and desirable case. It is only latched off by a delivery
  whose lease is still current, so a superseded turn cannot unlatch it for a
  live one.

Two consequences worth recording:

- **`run` drains in-flight turns when the inbound stream ends.** Desirable
  under [ADR-0019](0019-endpoint-session-reconnect-resume.md): the
  `EndpointSession` buffers while detached, so the reply survives to be
  replayed on reattach rather than being lost.
- **A delivery failure no longer kills the session.** It previously propagated
  out of `run`; now `_run_turn` records `turn_task_failed` on the Event Ledger
  and the session lives. This is a behavior change, not just a refactor.

`InMemoryEndpointSession.send` also gains an `asyncio.Lock`, shared with
`_flush_buffer`. Two independent writers became possible for the first time
(the frame loop sending the cancel frame, a turn task streaming audio), and
`_flush_buffer` replaying on reattach could already interleave with a live
`send` and put older buffered frames *after* newer live ones — the one ordering
guarantee ADR-0019's replay behavior depends on.

## Barge-in that actually cancels

`_resolve_dual_overlap` reacted to `ResponseAction.YIELD` with one statement:
`self._speaking_ms_remaining = 0.0`. `GenerationCounter.advance()` was called
in exactly two places in the Kernel, neither on the barge-in path. So the lease
stayed current and `StreamingSpokenResponseScheduler`'s per-chunk check never
tripped: the assistant talked over the user and finished its old answer.

Worse, the interrupting utterance was `peek_transcript()`ed but never consumed,
and τ9 lands in LISTEN with the VAD's onset tracker still holding
`_speaking = False` (SPEAK/DUAL only ever call `measure_chunk`). No end-of-turn
could ever close that utterance, so the user's words were discarded and they had
to repeat themselves.

`_yield_floor_to_user` now, in this order:

1. zeroes the speaking budget and clears `_awaiting_playback`;
2. **advances the Generation** — this is what stops the reply, since it is the
   signal every `ResponseScheduler` already checks, and the streaming scheduler
   `aclose()`s the vendor stream on it
   ([ADR-0012](0012-streaming-tts-as-a-separate-protocol.md));
3. supersedes any pending delegation, since a floor claim is a new topic under
   ADR-0008 — otherwise `_pending_session` stayed set and the next
   `UserTextFrame` would answer "still working on it" against a dead
   delegation;
4. sends `AssistantSpeechCancelledFrame` so the client drops audio it has
   already buffered;
5. **last, after every await**, re-arms the VAD
   ([ADR-0037](0037-re-armable-vad-utterances-and-client-reported-playback.md)),
   so no interleaved frame observes a half-applied yield.

The advance must precede the cancel frame so that a chunk send already suspended
in the turn task loses its lease before the client is told to drop audio.

`AssistantSpeechCancelledFrame` carries a generation because cancellation takes
effect at a *chunk boundary*: one more chunk for the interrupted generation can
already be in flight behind the cancel frame, and with two coroutines able to
write to the socket their relative order is not guaranteed. The client drops
audio matching the last cancelled generation
(`shouldDropAudioFrame` in `src/hooks/use-conversation-engine.ts`), or it would
play the interrupted assistant's tail *after* the barge-in.

**Correction to [ADR-0012](0012-streaming-tts-as-a-separate-protocol.md)
(2026-08-05).** That ADR closed with "No `ConversationKernel` or Turn Policy
change was needed … the Generation Lease already only goes stale once a new turn
is genuinely confirmed." That was wrong: nothing advanced the Generation on τ9,
so the per-chunk lease check it built could never trip on an actual barge-in.
The scheduler itself was correct and is unchanged; only the missing Kernel-side
advance is added. The clearest evidence it was never exercised end to end:
`tests/scheduler/test_streaming_spoken_response_scheduler.py` simulates a
barge-in with `on_yield=counter.advance`, manually doing the thing the Kernel
failed to do.

## What this does not fix

The survey's ~200ms yield bound is still unmet. `_resolve_dual_overlap` runs
when the overlap *ends*, so the earliest possible yield is after the user stops
talking, and the shipped `DefaultDualIntentClassifier`'s 800ms duration
threshold makes anything faster impossible by construction. Closing it needs an
early-yield or soft-yield (pause, classify, resume) design and its own ADR. See
[docs/INTERACTION-CASES.md](../INTERACTION-CASES.md) cell 3.

`_TABLE` still has no `(SPEAK, USER_EOT_CONFIRMED)` rule, so a `UserTextFrame`
arriving mid-reply is dropped — now easier to hit, and deferred to its own
commit as [ISSUE-0022](../ISSUES.md#issue-0022-a-text-frame-arriving-during-speakdual-is-silently-dropped).

## Testing

`tests/kernel/test_full_duplex_concurrency.py` is new and deliberately does
*not* settle turns between frames: `QueueTransport` injects frames into a
session that is mid-turn, and gated Brain/TTS doubles hold a turn open for as
long as a test wants. It asserts outcomes — that audio is read while the Brain
is deciding, that no chunk for the interrupted generation reaches the client
after the cancel frame, that the vendor stream was `aclose()`d, and that the
interrupting utterance is the one answered.

Every frame-scripted suite keeps its previous timeline semantics via
`FakeTransport.step_with` / `ScriptedTransport.step_with`, which settle each
frame's turn before the next. The pacing lives in the test doubles rather than
as a flag on the Kernel, so "these suites describe a frame-stepped timeline" is
an explicit, reviewable claim rather than a hidden assumption.

Verified against the real transport, not only in unit tests: a scripted
WebSocket client drove τ1 → τ3 → τ8 → τ9(YIELD), observed
`assistant_speech_cancelled` on the wire, and had its interrupting utterance
answered on the next generation. Note that this required substituting
`EnergyVad` for `SileroVad` — the live demo's neural VAD correctly rejects
synthetic tones as non-speech, so the barge-in path cannot be driven by a
scripted client against the shipped wiring at all
([ISSUE-0025](../ISSUES.md#issue-0025-the-live-demos-barge-in-path-cannot-be-exercised-without-real-speech-audio)).
