---
status: superseded
---

# EOT dual-scorer ensemble and split liveness bound

**Superseded (2026-08-10).** `EnsembleEotClassifier` remains an available
compatibility plugin, but it is not wired into the live voice path. The live
path is LLM-only, and wall-clock `wait_ms`/incomplete timeouts replace the
count-based liveness scheme. See [ADR-0057](0057-sentence-end-semantic-race-and-speculative-response.md)
and [Semantic EoT](../SEMANTIC-EOT.md). The remainder of this ADR is retained
as design history.

**Correction (2026-08-05).** The split liveness bound described below is real,
but its framing — "how many more silence-timeout cycles to tolerate" —
presupposed further cycles that the code could not produce, for the reason
corrected in [ADR-0013](0013-llm-semantic-eot-classifier.md). This ADR also
declined to re-arm `EnergyVad` as "a real change to its internals, not a
one-line addition"; that change is now made in
[ADR-0037](0037-re-armable-vad-utterances-and-client-reported-playback.md), so
the bound holds for the first time. Separately: `EnsembleEotClassifier` still
`await`s the slow classifier before returning, so the fast scorer can never
answer first and the ensemble buys accuracy but no latency, with no deadline on
the slow path — see [docs/LATENCY.md](../LATENCY.md) optimization 4.

`voiceagent/turn_policy/plugins/llm_eot_classifier.py`'s `LlmEotClassifier`
was single-model: one LLM call, fail-open to `COMPLETE` on error. Re-reading
`tmp/voiceloop-modular-runtime` (the in-repo checkout of `../realtime`)
found its `SemanticEoTProcessor` runs a fast always-on scorer (FireRedChat)
in parallel with an optional LLM judge and arbitrates asymmetrically: the
LLM wins except for one downgrade rule (LLM says incomplete, fast says
complete → `uncertain`), and it fails open to the fast result if the LLM
call fails. That ensemble shape is real and portable in spirit, unlike the
interruption-classifier claim corrected in ADR-0020.

**`voiceagent/turn_policy/eot_classifier.py`** gains, alongside the existing
`EotDecision`/`EotClassifier`: a `FastEotScorer` Protocol
(`async def score(self, *, text: str) -> EotDecision`) and
`PunctuationEotScorer`, a cheap, always-on, no-network stand-in for
FireRedChat — sentence-final punctuation (`.!?。！？`) reads as `COMPLETE`, a
trailing conjunction/connective as `INCOMPLETE`, anything else `UNCERTAIN`.

**`voiceagent/turn_policy/plugins/ensemble_eot_classifier.py`**'s
`EnsembleEotClassifier` composes an existing `EotClassifier` (the slow,
authoritative side — typically `LlmEotClassifier`, reused unmodified) with a
`FastEotScorer` (default `PunctuationEotScorer`). Both run concurrently via
`asyncio.gather`:

- slow raises → return the fast result (mirrors `LlmEotClassifier`'s own
  fail-open-to-`COMPLETE` discipline: a vendor hiccup on the slow side must
  never block forever).
- slow == `INCOMPLETE` and fast == `COMPLETE` → downgrade to `UNCERTAIN`
  (voiceloop's disagreement rule: don't end the turn on one confident signal
  alone when the other side disagrees).
- otherwise → the slow result is authoritative.

**Split liveness bound.** `voiceagent/kernel/conversation_kernel.py`'s
single `_eot_defer_count`/`eot_max_deferrals` cap is now two independent
counters: `eot_max_deferrals` (existing, default 1, for `INCOMPLETE`) and a
new `eot_uncertain_max_deferrals` (default 1, for `UNCERTAIN`).
`_should_defer_eot` checks/increments whichever counter matches the
decision kind; `COMPLETE` resets both to 0. This is the frame-driven,
deterministic analogue of voiceloop's `wait_ms` (short patience for
`uncertain`) vs. `incomplete_timeout_ms` (longer patience for `incomplete`)
— the same asymmetry, expressed as "how many more silence-timeout cycles to
tolerate" instead of wall-clock milliseconds, so it needs no new timer and
no `EnergyVad` surgery. This choice is deliberate, not incidental: ADR-0007
requires the Kernel's frame processing to stay deterministic (ticking down
using each chunk's own duration, not wall-clock timers), and ADR-0013 notes
that `EnergyVad`'s state machine already commits its own timer reset as a
side effect of returning `USER_EOT_CONFIRMED` — holding that open pending an
async judge would be a real change to its internals, not a one-line
addition.

Both changes are backward compatible: a classifier that only ever returns
`INCOMPLETE`/`COMPLETE` (like `LlmEotClassifier` alone, unchanged by this
ADR) behaves exactly as it did before — `eot_uncertain_max_deferrals` simply
never engages.
