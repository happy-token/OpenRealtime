---
status: accepted
amends: [0034, 0035]
---

# Use Silero VAD directly without Pipecat

OpenRealtime no longer installs or requires `pipecat-ai`. The framework already
owns its transport, turn-policy, conversation-engine, tool-orchestration, and
Agent-supervision contracts; pulling in Pipecat only to wrap one Silero VAD
implementation adds an unrelated pipeline abstraction without strengthening
those boundaries.

The default voice demo uses `SileroVad`, a small conformer that calls the
official `silero-vad` package directly. It lazily loads the official JIT model
with `load_silero_vad()`, converts signed PCM16 samples to normalized float32
tensors, and buffers transport audio into the model's exact supported windows:
512 samples at 16 kHz or 256 samples at 8 kHz. The model's recurrent state is
retained across consecutive windows and reset on a sample-rate change or
adapter shutdown.

Silero produces only the per-window speech probability. OpenRealtime's shared
`_OnsetEotTracker` remains authoritative for speech onset, hesitation/resume,
and end-of-turn timing. This keeps acoustic inference separate from dialogue
state and lets another VAD replace Silero through the existing `Vad` protocol.
`EnergyVad` remains available as a deterministic, dependency-light conformer
for isolated tests and explicit fallback use, but is not the live demo default.

The direct dependency is `silero-vad`, including its declared Torch runtime;
there is no Pipecat dependency, background event-loop bridge, or Pipecat VAD
state machine. A future direct ONNX conformer may be evaluated separately if
runtime footprint becomes a deployment constraint.

RTC remains unrelated and deferred. Removing Pipecat does not change the
canonical Conversation Engine, Turn Policy, or future transport adapter contract.
