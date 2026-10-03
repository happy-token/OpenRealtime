# Map elapsed playback time to original text proportionally, instead of matching provider word text literally

ADR-0132 and ADR-0133 fixed each vendor's word-timing *wiring* (which
event carries it, which flag enables it). Both still fed word timing into
`server/realtime/capabilities/tts.py`'s `_emit_audio`, which matched each
word's own text against the LLM's original text character by character:

```python
if accepted[aligned_text_end:].startswith(chunk.spoken_text):
    aligned_text_end += len(chunk.spoken_text)
```

Confirmed against real sessions with both vendors: a provider's per-word
`text` is a **pronunciation rendering**, not reliably a literal substring
of the original text — numbers become spelled-out digits (`"123"` ->
`"一百二十三"`, `"2026"` -> `"二零二六"`), currency symbols get expanded
and read aloud (`"¥99.9"` -> `"九十九点九元元"`), and Latin-script spacing
or casing can change (`"Hello World"` -> `"HelloWorld"`,
`"OpenRealtime"` -> `"openrealtime"`). The moment any of this appears,
the `startswith` match fails permanently — `aligned_text_end` never
advances again for the rest of that utterance, so every caption update
after that point silently stops. Playback eventually finishes and the
client's unconditional `finish()` fallback reveals the whole accumulated
text at once — the user-observed "aligned at first, then stops updating,
then everything pops out together" symptom.

**Decision**: stop matching word text against original text at all. Use
real elapsed time instead. Both vendors also return, per sentence, a
*sentence-level* text field confirmed to always equal the real original
text exactly (Doubao's `text` on 351/364, Bailian's `original_text` on
`result-generated`) plus the real total spoken duration of that sentence
(derived as the last word's end time). `SynthesizedAudioChunk` grew two
new fields — `sentence_text` and `sentence_duration_us` — carrying these.
`_emit_audio` now, when both are present: anchors the sentence's real
text to a position in the accumulated original text (via a single
`str.find`, not per-word matching), then maps `word.end_time /
sentence.duration` to a proportional offset within that sentence's
*real* text length. The result is always a position inside the real
original text — satisfying `delivery.py`'s invariant that delivered text
must be a prefix of intended text — without ever depending on the
provider's word text matching anything.

The old character-matching path is kept as a fallback for providers (or
test doubles) that supply per-word timing without a sentence-level
anchor; it is unchanged and still covered by the existing
`test_tts_sentence_metadata_becomes_a_separate_text_alignment_event` test.

**Rejected alternative**: display the provider's own pronunciation
rendering as the caption text (considered first, called out as "方案B"
during review). Rejected because `delivered_speech_transcript`
(`server/realtime/speech/delivery.py:55`) enforces `intended_spoken_content.
startswith(delivered_speech_transcript)` — delivered text must be a
literal prefix of the LLM's real original text, since it's reused as
authoritative context after an interruption (`InterruptedContextPolicy`).
A pronunciation rendering is not a substring of the original text, so
this would violate that invariant and break post-barge-in context
truncation, not just the caption.

**Verified against real production traffic** (not just unit tests): a
full real WS v2 session with `BailianTtsEngine` (the engine this
environment's `VOICEAGENT_TTS_BACKEND=bailian` actually selects), using
text containing both failure triggers at once ("Hello World" +
"第1句有数字123"), produced a continuously advancing sequence of
`assistant_text_alignment` frames through to the end of the sentence —
no stall, no single whole-sentence frame at the end.
