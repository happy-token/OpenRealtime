---
status: accepted
---

# Silero VAD is the live demo's sole VAD, no silent EnergyVad fallback

A comparison session against `../realtime` (VoiceLoop Agent) flagged OpenRealtime's VAD as a real
capability gap: `EnergyVad`'s RMS-threshold heuristic is materially weaker than a real neural VAD.
Re-reading `demos/voice_web_server.py._build_vad()` (added in
[ADR-0035](0035-silero-vad-and-live-demo-eot-interruption-wiring.md)) found it already preferred
`SileroVad`, but wrapped construction in a `try`/`except Exception` that silently fell back to
`EnergyVad` and only logged a warning.

That fallback made sense when `pipecat-ai[silero]` was a new, unproven addition — an unexpected
init failure (missing ONNX runtime, model download failure, etc.) shouldn't take the whole demo
down. It no longer earns its complexity: `pipecat-ai[silero]` (`pyproject.toml`) is an
unconditional dependency of this project, not an optional extra gated behind credentials the way
Bella/Doubao/ByteWebSearch are. Unlike those, there's no legitimate "credentials not configured"
reason for `SileroVad()` to fail at this point — any exception it raises now is a real bug (bad
install, corrupted model cache, breaking change in `pipecat-ai`) that a silent downgrade to a
strictly worse VAD would hide rather than surface.

## Decision

`_build_vad()` now unconditionally constructs and returns `SileroVad()` — no `try`/`except`, no
`EnergyVad` fallback path, no runtime `ImportError` handling. A construction failure now propagates
and fails demo startup loudly, the same way a broken `BellaAsrEngine`/`DoubaoTtsEngine` import would.

`EnergyVad` is unaffected as `server.kernel.ConversationKernel`'s own zero-dependency default
conformer (`vad or EnergyVad()`) — that default exists specifically so the framework and its ~50
existing unit tests (`tests/test_conversation_kernel.py`, `tests/bench/full_duplex_bench.py`, etc.)
keep a deterministic, no-model, no-inference VAD without needing to pass one explicitly. Only this
one live demo's default was tightened; the Protocol-level "deterministic default + optional real
conformer" pattern this framework uses everywhere else (`AsrEngine`, `TtsEngine`, `LlmClient`, ...)
is unchanged.

## Consequences

- `demos/voice_web_server.py` no longer imports `EnergyVad`/`Vad` at all — `_build_vad()` is
  annotated `-> SileroVad` directly.
- `tests/test_voice_web_server_wiring.py::test_build_vad_always_returns_silero_with_no_energy_vad_fallback`
  guards both that `_build_vad()` returns a `SileroVad` and that the module no longer references
  `EnergyVad`, so a future contributor can't quietly reintroduce the fallback.
- `basic_ws_server.py`/`udp_server.py` are unaffected — they're deliberately minimal wire-protocol
  demos (see their own module docstrings) that don't wire a real VAD/ASR/TTS pipeline at all and
  rely on the Kernel's `EnergyVad` default, which is correct for what they're proving.
