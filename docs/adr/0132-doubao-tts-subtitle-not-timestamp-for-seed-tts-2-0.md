# Doubao seed-tts-2.0 captions use `enable_subtitle`/`TTSSubtitle`, not `enable_timestamp`

`doubao_tts_direct.py` requests `enable_timestamp: true` and parses word
timing out of `TTSSentenceEnd` (event 351, with an unexplained `364` treated
as an alias). Volcengine's own bidirectional-TTS documentation states
`enable_timestamp` only takes effect for TTS1.0/ICL1.0; the configured
`DEFAULT_RESOURCE_ID = "seed-tts-2.0"` means that flag has never done
anything, and the `words` field has never been populated by the server —
not a parsing bug, a parameter mismatch with the active model version. The
reference client this integration was reverse-engineered from
(TEN-framework's `bytedance_tts_duplex`) also only speaks `enable_timestamp`
+ `TTSSentenceEnd`, confirming the `364` event code didn't come from there;
its origin is unconfirmed.

TTS2.0/ICL2.0 captions instead require `enable_subtitle` and arrive on a
distinct `TTSSubtitle` event, word-aligned to the original text (not a
text-normalized form), delivered non-blocking relative to audio (subtitles
for an already-sent sentence may arrive after later audio has already gone
out) — a materially different delivery contract than the TTS1.0 path this
code was built against.

**Decision**: keep `seed-tts-2.0` (its voice roster — `_uranus_bigtts` /
`saturn_` names — doesn't appear in TTS1.0 examples, and switching back
would risk losing voices already in use; this wasn't independently
re-verified, so treat it as the working assumption, not a confirmed fact).
Switch the alignment path to `enable_subtitle` + a dedicated `TTSSubtitle`
handler decoupled from `TTSSentenceEnd`, instead of reverting to
`seed-tts-1.0` to keep the already-working `enable_timestamp` path.

Rejected alternative: revert to `seed-tts-1.0`. Would keep the
already-verified `enable_timestamp`/`TTSSentenceEnd` shape, but requires
confirming voice-roster compatibility (unresolved) and reintroduces the
TTS1.0 quirk this code never handled either (`words` text is a
normalized/tn form, not the original text — a second, separate mapping
problem).

**Update (confirmed against a real `seed-tts-2.0` session, 2026-10-02):**
`364` is in fact `TTSSubtitle` — a live probe logged `event=364 resolved
per-word timing (words=23)` with real, monotonically increasing word
timestamps. `enable_subtitle` works as documented.

That same probe surfaced a second, previously undetected bug this fix
introduced: `TTSSentenceEnd` (351) always arrives first, always with an
empty `words` list, and the real per-word data arrives later on the
separate `TTSSubtitle` (364) event for the same utterance. The original
version of this fix still had `_alignment_chunks` eagerly emit a
whole-sentence fallback chunk whenever `words` was empty — which fired on
every single 351 event, racing ahead of 364's real data. On the client,
`PlaybackTextTimeline` picks the longest cue that has reached its
visibility threshold; the eager whole-sentence cue (no real timing, so
`audio_start_us=0`) becomes visible almost immediately and is always
longer than any individual word cue, so it visually overrides the real
per-word captions arriving right after it — reproducing the user-observed
"text and audio aren't in sync" symptom, now with text appearing *before*
its corresponding audio.

Fixed by removing the whole-sentence fallback from `_alignment_chunks`
entirely: it now only yields chunks when real per-word timing is present,
and logs (rather than guesses) when it isn't. The whole-utterance fallback
for "no word timing ever arrived in this response" already existed one
layer up, keyed off `ResponseCompleted`
(`server/realtime/transport/websocket.py:273-282`) — which cannot fire
prematurely, since it only runs once the whole response is known to be
done. `_alignment_chunks` duplicating that decision at the wrong time was
the actual bug; the event wiring (351 vs. 364) was correct from the start
of this ADR.
