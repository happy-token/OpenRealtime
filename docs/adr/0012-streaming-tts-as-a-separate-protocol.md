---
status: accepted
---

# Streaming TTS as a separate Protocol, scheduler, and frame type

**Correction (2026-08-05).** The claim below that "no `ConversationKernel` or
Turn Policy change was needed" was wrong. Nothing advanced the Generation on τ9,
so the per-chunk lease check this ADR introduced could never trip on an actual
barge-in — the assistant streamed its whole reply over the interrupting user.
The scheduler itself is correct and unchanged; the missing Kernel-side advance is
added in
[ADR-0036](0036-concurrent-turn-execution-and-real-barge-in-cancellation.md).

`SpokenResponseScheduler` synthesizes one whole-utterance `SynthesizedAudio`
blob per reply and sends it as a single `AssistantAudioFrame`. Once
synthesis starts there is no way to stop it partway through — a barge-in
landing mid-synthesis could already be caught (re-checking the Generation
Lease after `synthesize()` returns, before sending), but the vendor call
itself always ran to completion and paid for/buffered audio nobody would
hear. `DoubaoTtsEngine`'s Bella-gateway connection already receives
`SpeechAudioDelta` events one at a time; the code just buffered them all
before returning.

We added `StreamingTtsEngine` (`speech/tts.py`) as a **separate** Protocol
from `TtsEngine`, rather than adding a `synthesize_stream` method to
`TtsEngine` itself — mirroring the existing `AsrEngine`/`AsrSession` split
being distinct from the simpler `TtsEngine` shape. Likewise
`AssistantAudioChunkFrame` is a new frame type alongside the untouched
`AssistantAudioFrame`, and `StreamingSpokenResponseScheduler` is a new
scheduler alongside the untouched `SpokenResponseScheduler`. The
alternative — overloading the existing Protocol/frame/scheduler — would
have made every existing whole-utterance conformer, test, and caller
responsible for a streaming case it doesn't need. Keeping them separate
means the whole-utterance path (`TtsEngine`, `AssistantAudioFrame`,
`SpokenResponseScheduler`, and all their tests) is unchanged, byte for
byte; streaming is an explicit opt-in a caller chooses by constructing a
different scheduler with a different engine.

`StreamingSpokenResponseScheduler` re-checks `lease.is_current()` before
sending *every* chunk, not just once before starting synthesis. On the
first stale check it calls `chunk_stream.aclose()` and stops — closing an
async generator that is suspended inside `DoubaoTtsEngine`'s
`async with connect(...) as connection:` block triggers that block's
`__aexit__`, tearing down the Bella WebSocket immediately. This is real
mid-stream cancellation, not a client-side frame filter: the vendor stops
being asked to produce audio the instant a barge-in is confirmed. No
`ConversationKernel` or Turn Policy change was needed to support this —
the Generation Lease already only goes stale once a new turn is genuinely
confirmed (not on mere audio-energy overlap during SPEAK/DUAL), which is
exactly the same signal `ImmediateResponseScheduler` already gates text
delivery on.
