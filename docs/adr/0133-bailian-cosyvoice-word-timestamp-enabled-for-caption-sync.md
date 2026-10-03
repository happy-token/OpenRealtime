# Bailian CosyVoice needs `word_timestamp_enabled`, not Doubao's protocol — this is the TTS backend actually configured

ADR-0132 fixed Doubao TTS2.0's word-timing wiring (`enable_subtitle`/
`TTSSubtitle`), based on correct protocol research and real verification
against `DoubaoDirectTtsEngine`. That work was not wrong, but it targeted
the wrong engine: this environment's `.env` sets
`VOICEAGENT_TTS_BACKEND=bailian`, so `demos/voice_web_server.py`'s
`_build_tts_engine()` actually selects `BailianTtsEngine` (Alibaba Cloud
Bailian/DashScope CosyVoice), never touching `doubao_tts_direct.py` at
all. A full real end-to-end WS v2 session produced only one whole-sentence
`assistant_text_alignment` frame (the `ResponseCompleted` fallback); the
`doubao_tts_direct` logger had zero entries for that session, proving the
Doubao code path was never exercised — the actual backend choice should
have been confirmed before investigating any vendor's protocol.

**Decision**: fix `server/speech/plugins/bailian_tts.py` to request and
parse CosyVoice's own word-timing mechanism, confirmed against Aliyun's
own docs (help.aliyun.com/zh/model-studio/cosyvoice-client-events and
cosyvoice-server-events):

- Request `word_timestamp_enabled: true` in `run-task`'s `parameters`.
  Defaults to `false`; only takes effect in streaming mode; only for a
  documented subset of models/voices (`cosyvoice-v3.5-plus`,
  `v3.5-flash`, `v3-flash`, `v3-plus`, `v2` cloned voices, or system
  voices marked as supporting it). The configured `cosyvoice-v3-flash`
  is in that supported set.
- Word timing arrives on the `result-generated` event's
  `payload.output.sentence.words` array, but only once
  `payload.output.type === "sentence-end"` — `sentence-begin` and
  `sentence-synthesis` always carry an empty `words` list for the same
  event name.
- `words[].text` is the original character (not a normalized/tn form
  the way Doubao TTS1.0's is); `begin_time`/`end_time` are milliseconds.
- Requesting this flag for an unsupported voice is a silent provider-side
  no-op (empty `words`), not an error — the code must never assume
  "the flag was sent, so timing must be present."

Mirrors ADR-0132's architectural rule: the new `_alignment_chunks` in
`bailian_tts.py` only yields chunks when real per-word timing is present
and only logs (never guesses a whole-sentence fallback) when it isn't.
That decision belongs to `ResponseCompleted`
(`server/realtime/transport/websocket.py`), one layer up, which cannot
fire prematurely.

**Verified against the real production engine** (not just protocol
reading): a direct `BailianTtsEngine.synthesize_duplex` probe produced 25
real per-character timestamps; a full real WS v2 session produced
multiple progressively-cumulative `assistant_text_alignment` frames
("你" → "你好" → "你好，" → …) instead of one whole-sentence frame.

## Lesson

Before investigating a third-party vendor's protocol for a bug report,
confirm which configured implementation the running environment actually
uses. `VOICEAGENT_TTS_BACKEND` (or the equivalent selector for any
pluggable capability) is the first thing to check — a correct, well-
verified fix against the wrong backend fixes nothing a user can observe.
