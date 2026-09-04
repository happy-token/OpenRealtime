---
status: accepted
---

# Replaceable EoT evidence providers and DeepSeek Responses

## Context

Semantic endpointing originally exposed three overlapping shapes:
`EotClassifier.classify`, `ContextualEotClassifier.classify_with_context`, and
`FastEotScorer.score`. The fast shape discarded probability, latency, and
provider identity, while the legacy ensemble could allow punctuation to end a
turn without a semantic judgement. FireRedChat also cannot replace a
history-aware judge for short contextual answers.

DeepSeek now supports the stateless OpenAI Responses format, including
semantic SSE events and strict JSON Schema output. The public OpenRealtime
Realtime protocol already has `RequestResponse` and response lifecycle events;
provider HTTP transport must not leak into that interface.

## Decision

The public Realtime command/event contract remains unchanged. The existing
OpenAI-compatible LLM adapter gains an internal `api_style` selection. Only
semantic EoT defaults to DeepSeek `/responses`; ordinary Brain and tool paths
remain on Chat Completions. EoT sends full bounded history on every stateless
request, disables thinking, and requests the `semantic_eot` JSON Schema.

Inside the Cascaded Turn Manager, `EotEvidenceProvider` is the replaceable
seam. A provider evaluates one immutable `EotRequest` and returns
`EotEvidence` with decision, confidence, optional end probability, source, and
inference time. Existing classifiers use an adapter. FireRedChat is an ONNX
adapter loaded once at application startup and shared across conversations.

`HybridEotClassifier` remains the deep module for parallel evidence and
arbitration. It supports:

- `primary_with_shadow`: the first provider decides, secondary evidence is
  retained, and a secondary provider is used only when the primary fails;
- `consensus`: complete/incomplete disagreement becomes `UNCERTAIN`.

The default FireRed path is instead the sequential
`FastCompleteFallbackEotClassifier`: FireRed can return `COMPLETE` without a
network call only when its probability reaches the configured threshold and a
conservative Chinese closure guard recognizes an explicitly closed question,
confirmation, or closing expression. Every local `INCOMPLETE`, low-confidence
result, open expression, or local failure invokes the contextual LLM provider.
An LLM `COMPLETE` is still vetoed for a small set of unambiguous open-slot
endings. `primary_with_shadow` and `consensus` remain explicit rollback and
comparison modes. Punctuation short-circuiting in the legacy ensemble is
opt-in rather than default.

## Evidence

On 2026-08-14, 30 paired DeepSeek EoT calls produced:

| Transport | Valid | Label agreement | Parse p50 | Parse p95 |
|---|---:|---:|---:|---:|
| Chat Completions | 30/30 | 27/30 | 787ms | 1048ms |
| Responses | 30/30 | 28/30 | 776ms | 1032ms |

Responses was only slightly faster; strict JSON Schema and semantic SSE were
the deciding reliability benefits.

The FireRedChat Chinese q8 model loaded in about 2.85s and inferred at p50
44.38ms / p95 45.05ms on the development machine. On the project-owned,
balanced 100-case Chinese v1 evaluation set, raw threshold 0.5 accuracy was
67%, false-cutoff rate 46%, and missed-endpoint rate 20%. Threshold increases
alone did not produce a safe operating point: even 0.9995 retained a
high-confidence false cutoff.

The conservative fast-complete guard accepted 8/100 cases with 100% precision.
The configured sequential runtime then evaluated the remaining 92 with
DeepSeek Responses. One recorded run after the LLM open-slot veto achieved
100% complete precision, 0% false cutoffs, and 0% missed endpoints, with
end-to-end classifier p50 927.79ms / p95 1237.54ms. This is an in-sample v1
capability result, not a production generalization claim; an independently
adjudicated real-conversation set remains a release prerequisite.

## Consequences

New EoT methods can be added without modifying Semantic Endpoint Gate, Turn
Policy, Realtime Engine, or the public Response protocol. Switching the LLM
transport is independently reversible with `VOICEAGENT_EOT_LLM_API_STYLE`.
The fast path saves the network classification only for conservatively closed
expressions; most turns intentionally pay LLM latency to protect against user
interruption. FireRedChat adds no base dependency; ONNX and Transformers remain
in the optional `firered` extra, and model weights stay outside the repository.
