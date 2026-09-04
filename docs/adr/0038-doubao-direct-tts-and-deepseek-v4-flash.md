---
status: accepted
---

# Doubao direct bidirectional TTS (supersedes ADR-0011's "confirmed broken"), explicit deepseek-v4-flash with thinking disabled

The user wants OpenRealtime's speech/LLM vendors talking directly to official
APIs instead of through the internal Bella gateway wherever practical —
"后面可能需要把接口做一下替换。之前的接口是做了一层网关转发" (we may need to
swap the interface later; the previous interface routed through a gateway
layer). Two gaps remained after ADR-0011: TTS was still Bella-gateway-only,
and the LLM model/thinking config relied on an implicit alias.

**TTS.** ADR-0011 marked the direct Volcengine V3 bidirectional endpoint
(`wss://openspeech.bytedance.com/api/v3/tts/bidirection`) "confirmed
broken — connects, but never responds to any binary-protocol variant
tried." The user explicitly rejected falling back to the unidirectional
HTTP alternative — "我不要 HTTP 接口，我要双流式接口" (I don't want the HTTP
interface, I want the bidirectional streaming interface) — so the actual
protocol gap needed to be found and fixed, not routed around.

The root cause: every prior attempt framed requests with the ASR-style
`MsgTypeFlagPositiveSeq`/`NoSeq` flags. The bidirectional TTS endpoint
instead requires `MsgTypeFlagWithEvent` (`0b0100`) plus a full
connection/session/task **event lifecycle** — numeric event codes
(`StartConnection`=1, `ConnectionStarted`=50, `StartSession`=100,
`SessionStarted`=150, `TaskRequest`=200, `TTSSentenceStart`=350,
`TTSResponse`=352, `TTSSentenceEnd`=351, `SessionFinished`=152,
`FinishConnection`=2, `ConnectionFinished`=52) carried in the frame body
ahead of an optional session-id field and an optional payload. This is a
different framing convention than the ASR endpoint, not a broken or
undocumented server. A throwaway spike script (`_build_frame`/`_parse_frame`
plus the connect→session→task→audio→finish sequence, run against the real
endpoint with `DOUBAO_API_KEY` and deleted immediately after) confirmed it
end-to-end: 124,828 bytes of real PCM16 audio came back over eight
`TTSResponse` frames.

`server/speech/plugins/doubao_tts_direct.py` (`DoubaoDirectTtsEngine`) is
the production conformer, mirroring `doubao_tts.py`'s/`doubao_asr.py`'s
shape and reusing `DoubaoTtsError` rather than defining a second exception
type. It deliberately supports only the single-key auth path
(`DOUBAO_API_KEY`/`X-Api-Key`) that's proven to work — not the legacy
app_id/token headers ASR uses, since nothing needs that path here (YAGNI).
Covered by pure protocol tests (`tests/speech/test_doubao_tts_direct_protocol.py`),
fake-WebSocket engine tests (`tests/speech/test_doubao_tts_direct.py`), and
a skip-by-default live smoke test against the real endpoint
(`tests/live/test_doubao_direct_tts_live.py`, passes under `RUN_LIVE=1`).

The backend is now a runtime choice, not a hardcoded one:
`demos/voice_web_server.py`'s `_build_tts_engine()` reads
`VOICEAGENT_TTS_BACKEND` (default `"doubao-direct"`; `"bella"` opts back
into the gateway path via `DoubaoTtsEngine`). ASR was unchanged by this
ADR — it still went through Bella in this demo; `doubao_asr.py`'s direct
conformer existed but wasn't wired into this demo's factory. See
ADR-0039: ASR now defaults to the direct conformer too.

**LLM.** `VOICEAGENT_LLM_MODEL` is now explicitly `deepseek-v4-flash`
instead of the `deepseek-chat` alias, and a new `disable_thinking`
constructor param (falling back to the `VOICEAGENT_LLM_DISABLE_THINKING`
env var when unset) makes both `OpenAiCompatibleLlmClient` and
`OpenAiCompatibleToolCallingLlmClient` send an explicit
`"thinking": {"type": "disabled"}` request field, rather than depending on
the alias's undocumented default. The field is omitted entirely when the
flag is false, so the existing Bella gateway path — which never sets this
env var — sends byte-for-byte the same request body it always has.
Confirmed against the real DeepSeek API: `model=deepseek-v4-flash` +
`thinking:{"type":"disabled"}` is accepted and returns a normal streamed
response with no reasoning content.

## Connection lifecycle amendment (2026-08-09)

The direct TTS conformer now scopes one vendor WebSocket to one logical Voice
Session instead of opening a new WebSocket for every text segment. Connection
and synthesis-session ownership are deliberately separate:

1. `StartConnection` is sent lazily once, before the first synthesis request.
2. Every segment uses a unique, serial
   `StartSession → TaskRequest → FinishSession` lifecycle on that connection.
3. A session lock prevents frames from concurrent turns or segments being
   interleaved on a provider connection that expects ordered sessions.
4. If a reused socket is stale, synthesis reconnects once only when no audio
   has been emitted. It never retries after audio starts, avoiding duplicated
   spoken output.
5. Voice Session shutdown propagates through Kernel → turn coordinator →
   Conversation Engine → TTS adapter, which sends `FinishConnection` and then
   closes the socket. Provider-initiated idle closure is treated as a
   best-effort shutdown condition.

A live two-segment probe against the real endpoint returned 63,182 and 57,582
PCM bytes over the same engine connection. In that single sample the cold
request took 3,386ms and the reused request 1,278ms. These numbers verify the
protocol and the avoided handshake; they are not an SLO or a general latency
claim.

## Duplex input amendment (2026-08-13)

ADR-0062 supersedes the per-segment synthesis lifecycle above for the live
Conversation Engine path. One assistant response now uses one
`StartSession → TaskRequest × N → FinishSession` lifecycle: raw, non-empty LLM
SSE deltas are incremental TaskRequests while provider audio is received
concurrently. `synthesize_stream(text)` remains compatible for older schedulers.
