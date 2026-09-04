---
status: accepted
---

# Bella-backed browser voice demo

The existing demos (`examples/client.py`/`server.py`) are text-only: no
browser frontend, no real ASR, and `EchoLlmClient` as the default LLM
stand-in. The user tried them and asked for an actual "语音交互产品" (voice
interaction product) — something they can talk to in a browser — and
directed that it be backed first by the company-internal Bella OpenAPI
gateway, the same way the sibling `../realtime` project uses it: one
unified `API_KEY` + `base_url` across ASR/TTS/LLM, swappable later.

This ADR covers `voiceagent/speech/plugins/bella_asr.py` (a new `AsrEngine`
conformer), `examples/voice_web_server.py`, and `examples/web/` (a plain
HTML/JS frontend, no build step).

## `BellaAsrEngine`: wire protocol

Bella's ASR endpoint (`wss://bella-openapi.ke.com/v1/audio/asr/stream`) is a
JSON NLS-style control-message-plus-raw-binary-audio WebSocket protocol,
distinct from Doubao's binary-framed protocol (`speech/doubao_asr.py`).
`BellaAsrEngine`/`BellaAsrSession` port the wire protocol from
`../realtime/server/bridges/bella_stt.py` (voiceloop's real client for the
same endpoint):

- `StartTranscription`/`StopTranscription` control messages: a JSON
  `header` (`message_id`, `task_id`, `namespace: "SpeechTranscriber"`,
  `name`, `appkey`) plus a `payload`. `appkey` is an arbitrary
  app-identifier string, not a credential — voiceloop uses `"voiceagent"`'s
  analogue there ("voiceloop"); this conformer uses `"voiceagent"`.
- The server's `TranscriptionStarted` response echoes back a `task_id` in
  its header, which is captured and reused for the later
  `StopTranscription` call — the client-generated `task_id` sent in
  `StartTranscription` is not guaranteed to be the one the server expects
  back.
- Audio is streamed as raw binary PCM directly over the WebSocket — no
  JSON/binary envelope, simpler than Doubao's framing.

voiceloop's own client carries substantial additional machinery this port
deliberately does not adopt: reconnect-on-idle, dual stall-clocks, and
finalization-recovery, all there because voiceloop's ASR client is directly
wired into pipecat's turn-taking. `speech/asr.py`'s own docstring already
establishes that Turn Policy/`EnergyVad` are OpenRealtime's sole end-of-turn
authority — an `AsrSession` only ever answers "what did they say," so none
of that resilience machinery has anywhere to plug in here. This mirrors the
same simplification `DoubaoAsrEngine` already made (ADR-0011).

## One shared `API_KEY` across ASR, TTS, and LLM

Confirmed directly against the sibling `../realtime` project
(`server/app_config.py`, `server/tests/benchmark_kv_cache.py`): its own
Bella-gateway credential is `env_vars.get("API_KEY")` — the exact same
environment variable `DoubaoTtsEngine` (ADR-0011) already reads in this
repo. `examples/voice_web_server.py` builds `BellaAsrEngine`,
`DoubaoTtsEngine`, and an `OpenAiCompatibleLlmClient` pointed at
`https://bella-openapi.ke.com/v1` (model `gpt-5.6-sol`, the sibling
project's own production default) all from that one variable. No new env
var was introduced for this feature.

## Frontend: plain HTML/JS, no framework

The sibling `../realtime/web` is a full Next.js app plus a published
`web-sdk` npm package — too heavy for "just a demo" and contrary to this
project's stdlib/no-new-dependency discipline (`pyproject.toml` has only
`pydantic`+`websockets`). `examples/web/` is a small vanilla page instead,
served by a stdlib `http.server.ThreadingHTTPServer` alongside the existing
WebSocket server, so `uv run python examples/voice_web_server.py` is the
one command that runs the whole demo.

Two implementation choices worth recording:

- **Continuous streaming, not push-to-talk.** A single toggle starts/stops
  mic capture; while on, audio streams continuously and the Kernel's own
  Turn Policy/VAD decide end-of-turn. Push-to-talk would sidestep the exact
  full-duplex behavior this demo exists to show off.
- **Downsampling happens in JS, in an `AudioWorkletProcessor`
  (`pcm-worklet.js`), not via `AudioContext({sampleRate: 16000})`.**
  Browsers don't reliably honor a requested context sample rate; the
  worklet instead receives native-rate Float32 frames, linearly resamples
  to 16 kHz, converts to Int16, and posts PCM back to the main thread,
  which base64-encodes it into the existing `AudioChunkFrame` shape
  (`transport/frames.py`). Playback (`app.js`) reads `sample_rate_hz` off
  each inbound frame rather than hardcoding it (Bella/Doubao TTS emits
  24 kHz) and lets `AudioContext` resample automatically via
  `createBuffer(1, n, sampleRateHz)`; it tracks `generation` and stops all
  currently-scheduled `AudioBufferSourceNode`s the instant a new
  generation's audio arrives, for real barge-in.

## Scope not implemented

- No reconnect if the Bella ASR gateway closes the socket after a
  `TranscriptionCompleted` event — unconfirmed whether it does this
  in practice for this NLS-style backend; `DoubaoAsrSession` makes the same
  simplification today. Flagged for the live manual-smoke pass; a cheap,
  narrow follow-up (reconnect inside `push_audio`) if it turns out to
  matter, not a blocker for landing this.
- No auth, CORS, or TLS hardening on either server — this is a local demo
  bound to `0.0.0.0`/`localhost`, not a deployable product surface.
- No mobile/touch-specific UI treatment — desktop Chrome is the target for
  this demo.
