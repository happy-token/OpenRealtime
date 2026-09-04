---
status: accepted
---

# Content-aware DualIntentClassifier, extending the existing Protocol rather than adding a new plugin layer

ADR-0007 shipped `DualIntentClassifier` with a duration-only default because
"the audio-only path has no ASR transcript to classify on in v1," and
explicitly anticipated the fix: "real deployments with ASR wired up should
register a content-aware classifier instead." That wiring didn't exist yet:
`_handle_audio_during_speak`/`_handle_audio_during_dual` in
`ConversationKernel` only ever called `EnergyVad.measure_chunk(...)` — never
`AsrSession.push_audio(...)` — so no transcript ever accumulated once Turn
Policy left LISTEN, no matter what `AsrEngine` was configured.

Unlike ADR-0013's `EotClassifier`, which needed a brand-new Kernel-level gate
because `EnergyVad`/`TurnPolicy` had no hook at all for that decision, here
the right hook already existed: `DualIntentClassifier.classify()` is already
consulted at exactly the point (`_resolve_dual_overlap`) where a
content-aware decision belongs, and its own governing ADR already anticipated
this evolution. So this change extends the existing Protocol with a required
`text: str` param instead of introducing a second plugin layer alongside it.
No new `AsrSession` method was needed either — `peek_transcript()` already
exists (added for `EotClassifier`) and is non-destructive by design, so
`_resolve_dual_overlap` reuses it unchanged.

`_feed_asr_session` creates the ASR session lazily in SPEAK/DUAL too, not
only in LISTEN's existing default branch. A session can reach SPEAK before
any prior LISTEN chunk ever created one — e.g. a proactive or
delegation-ack response that plays before the user has said anything yet in
this connection — so gating session creation on "we're past LISTEN" would
silently drop that audio.

`_resolve_dual_overlap` never drains or consumes the peeked transcript on
either classification outcome. On FLOOR_CLAIM (τ9 → LISTEN), the text must
stay buffered: it's the start of the user's real next turn, and the
ordinary LISTEN path's later `consume_transcript()` call at genuine EOT is
what should finally claim it — draining it here would let a real reply
disappear before the EOT classifier or Brain ever sees it. On BACKCHANNEL
(τ10 → SPEAK continues), nothing needs discarding either: `DoubaoAsrSession`
overwrites `_transcript` on each new server response rather than appending,
so a stray "嗯" is naturally superseded once the next real utterance's
transcript arrives; `_PreloadedAsrSession` and its test doubles follow the
same last-write-wins shape. Adding drain/consume logic here would be
speculative complexity with no scenario that needs it.

`LlmDualIntentClassifier` is built entirely on the existing `LlmClient`
Protocol (`brain/llm_clients.py`) — the same seam `LlmEotClassifier` and
`ChatBrain` already use, no new vendor or dependency. It prompts for a
six-label taxonomy (`stop`/`correction`/`interrupt`/`backchannel`/`ignore`/
`uncertain`), inspired by voiceloop's `semantic_interruption.py`, even though
`DualIntent` itself stays binary — Turn Policy's transition table only has
τ9/τ10 as DUAL-classification destinations, so there is nothing to gain from
widening the enum. `stop`/`correction`/`interrupt` collapse to FLOOR_CLAIM,
`backchannel` to BACKCHANNEL. Empty text, `ignore`/`uncertain`, and any
unparseable reply all delegate to an injectable `fallback: DualIntentClassifier`
(defaulting to `DefaultDualIntentClassifier()`) rather than hardcoding a
fixed direction. Falling back to a mechanical, already-shipped signal
(duration) rather than "always yield" or "always continue" keeps this
consistent with `LlmEotClassifier`'s fail-open discipline, just routed to an
existing heuristic instead of a fixed constant.

No classifier is registered by default and `ms_per_char`/duration-heuristic
behavior is unchanged when unregistered — this is purely additive.

**Correction (2026-08-03, see ADR-0020):** the paragraph above originally
claimed this fallback discipline "mirrors voiceloop's own
`apply_interruption_threshold`, which downgrades low-confidence stop-labels
to 'uncertain'." An exhaustive grep of `tmp/voiceloop-modular-runtime` found
no such method and no confidence-threshold classifier anywhere in that
codebase — voiceloop's actual interruption mechanism is a static
`interrupt_strategy` config choice (`"transcript"` vs `"vad"`) plus an
unused, never-invoked `backchannel_classifier` stub. The fallback discipline
described above is original OpenRealtime design, not a port. ADR-0020 adds a
real confidence-threshold demotion (loosely inspired by voiceloop's
filler-gate `RuleMatcher` shape instead) and documents the correction in
full.
