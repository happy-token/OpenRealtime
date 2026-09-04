---
status: accepted
date: 2026-08-10
---

# Use Doubao `bigmodel` as the default ASR endpoint

## Context

The direct Doubao ASR adapter originally defaulted to the optimized
`bigmodel_async` endpoint. Small exploratory runs were not sufficient for an
endpoint decision because connection routing and a machine-level proxy produced
large, inconsistent WebSocket handshake and response tails.

The external latency metric also needed a precise name. Doubao does not expose
its decoder's internal token events. The observable streaming metric is the
time from the first audio packet to the first server response containing
non-empty recognized text. One response may contain multiple characters, so
this repository calls it **ASR first increment**, not **ASR first token**.

## Controlled comparison

On 2026-08-10 both endpoints were tested 30 times with application-level proxy
discovery explicitly disabled. The test alternated endpoint order and created a
fresh ASR WebSocket for each attempt. Every one of the 60 requests reused the
same PCM bytes:

| Input property | Value |
|---|---|
| Transcript | `你好，请介绍一下自己` |
| Format | PCM16 mono, 16 kHz |
| Audio duration | 1966.1ms |
| Packet size/cadence | 200ms |
| PCM SHA-256 | `2082063adaa534d8b85ffa54fff19d8c415fb01b8eddabcf4ee075097a19d4c1` |

The first non-empty increment was `你好` in all 60 successful requests. It was
two Chinese characters in one provider update, which confirms that the external
event is not a single model token.

| Metric | `bigmodel` | `bigmodel_async` |
|---|---:|---:|
| Success and exact transcript | 30/30 | 30/30 |
| WebSocket connect p50 / p95 | 79.6ms / 135.9ms | 78.8ms / 108.2ms |
| ASR first increment p50 / p95, excluding connect | 607.2ms / 773.4ms | 605.3ms / 748.1ms |
| ASR first increment p50 / p95, including connect | 699.1ms / 918.7ms | 688.4ms / 825.6ms |
| Audio end to provider final p50 / p95 | **161.9ms / 285.1ms** | 311.0ms / 471.6ms |

Earlier proxy-affected batches remain useful evidence that network routing can
dominate tail latency, but they are not used to choose the default endpoint.
Their WebSocket connect p50 was about 790ms, versus about 79ms in this direct
run.

## Decision

`DoubaoAsrEngine` defaults to:

```text
wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
```

The provider-neutral `AsrEngine`/`AsrSession` contracts, binary protocol,
authentication resource, 300ms endpoint window, revision model, and semantic
endpoint gate do not change.

> Follow-up (2026-08-13): the live demo reduced the configurable endpoint
> window and compared 96/128/150ms with one continuous synthesized utterance
> containing inserted 80/120/160/220ms pauses. 96ms finalized at all four
> pauses, 128ms at 120ms and above, and 150ms at 160ms and above. The default
> is therefore 150ms: its maximum 54ms delay relative to 96ms is much smaller
> than observed provider/model variance, while it avoids extra semantic and
> speculative-response requests on 80–120ms natural pauses. Because
> `result_type=single` may still finalize multiple segments inside one user
> turn, the adapter accumulates definite segments instead of replacing them.
> This does not alter the endpoint comparison recorded by this ADR.

> Operational follow-up (2026-08-13): a production-style session with a
> 150ms provider window produced 24 endpoint candidates for 8 committed turns,
> invalidated 15 candidates, and timed out all 8 stable remote semantic EoT
> decisions. The deployment default is therefore raised to 256ms and aligned
> with the external Silero window. This is an anti-fragmentation operational
> choice based on the session trace; the controlled 96/128/150ms comparison
> below remains historical evidence rather than being rewritten.

Endpoint choice remains replaceable at the adapter boundary:

1. An explicit `DoubaoAsrEngine(ws_url=...)` argument has highest priority.
2. `DOUBAO_ASR_WS_URL` can override the deployed endpoint without code changes.
3. With neither override, `bigmodel` is used.

`bigmodel_async` remains a supported operational fallback at
`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`.

## Observability contract

Latency dashboards and future benchmarks must keep the time bases separate:

| Metric | Start | End |
|---|---|---|
| `asr.connect_ms` | WebSocket connection attempt | WebSocket ready |
| `asr.first_increment_ms` | first audio packet sent | first non-empty recognized-text update |
| `asr.first_increment_e2e_ms` | WebSocket connection attempt | first non-empty recognized-text update |
| `asr.sentence_final_ms` | actual input audio end | provider `definite` sentence-final event |
| `llm.first_token_ms` | committed/speculative LLM request | first non-empty LLM content delta |
| `tts.first_audio_ms` | first text delta submitted | first synthesized audio bytes |

ASR first increment and LLM first token are deliberately different metrics.

## Consequences

- The default endpoint favors faster and tighter sentence-final latency while
  preserving essentially identical first-increment latency in the controlled
  direct-network run.
- Deployments can switch endpoints without changing the Conversation Kernel or
  the Speech Seam interface.
- Proxy/VPN state must be recorded with every future latency benchmark. A
  machine-level full-tunnel route cannot necessarily be bypassed by setting a
  WebSocket client's proxy argument.
- This decision concerns the current external ASR pipeline. It does not claim
  knowledge of private GPT Voice internals.
