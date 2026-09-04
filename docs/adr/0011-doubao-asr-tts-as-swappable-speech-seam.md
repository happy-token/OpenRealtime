---
status: accepted
---

# Real Doubao (火山引擎) ASR/TTS, behind swappable AsrEngine/TtsEngine Protocols

The user asked to move off the v1 "simulated ASR text / no TTS" placeholder and
wire in a real speech vendor — Volcengine's 豆包 (Doubao) models specifically,
with credentials from `.env` and the wire protocol documented in the sibling
`../bench` repo — "一定要设置为可替换，未来可能使用其他模型" (must be
replaceable, another vendor may be used in future). We introduced two new
Protocols, `AsrEngine`/`AsrSession` (`speech/asr.py`) and `TtsEngine`
(`speech/tts.py`), each with a deterministic default (`PreloadedAsrEngine`,
`SilentTtsEngine`) and one real conformer (`DoubaoAsrEngine`, `DoubaoTtsEngine`).
A future vendor swap is a new conformer only — zero changes to
`ConversationKernel` or `ResponseScheduler`.

TTS required no `ConversationKernel` change at all: `SpokenResponseScheduler`
wraps the existing `ResponseScheduler` Protocol, so a vendor is chosen entirely
at construction time. ASR required one narrow, deliberate change — routing the
audio-only path in `_handle_audio_chunk` through Router once EOT fires — because
Turn Policy/`EnergyVad` remain the sole end-of-turn authority. Doubao ASR's own
`definite:true` endpointing marker is read only to know which server frames
carry finalized text; it is never surfaced as a Turn Policy signal. This avoids
two competing EOT authorities and keeps the existing "L0, pluggable-module"
framing intact.

TTS deliberately does **not** use the direct Volcengine V3 endpoint that
`.env`'s `DOUBAO_TTS_WS_URL`/`DOUBAO_RESOURCE_ID` point at — that endpoint is
confirmed broken (connects, but never responds to any binary-protocol variant
tried; see `../bench/docs/issues/tts-protocol-debug.md`). Those two `.env` vars
are intentionally unused. `DoubaoTtsEngine` instead speaks doubao-seed-tts-2.0
through the company-internal Bella OpenAPI gateway
(`wss://bella-openapi.ke.com/v1/audio/tts/stream`), a plain JSON-over-WebSocket
protocol authenticated with the existing `API_KEY`, confirmed working in
`../bench/tts_benchmark.py` (30/30 success).

**Update (ADR-0038):** the direct Volcengine V3 bidirectional endpoint
described above as "confirmed broken" was later found to need a different
framing convention (`MsgTypeFlagWithEvent` plus an event-lifecycle
handshake) than the ASR-style flags every prior attempt used — not a broken
or undocumented server. It now works and is the default TTS backend; see
ADR-0038 for the protocol details and the `VOICEAGENT_TTS_BACKEND` switch
that keeps this Bella path available as an opt-in fallback.
