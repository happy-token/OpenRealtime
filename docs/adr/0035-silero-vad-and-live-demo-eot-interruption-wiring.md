---
status: accepted
---

# Silero VAD conformer, plus wiring semantic EOT and semantic interruption into the live demo

> **Renumbered 2026-08-05.** This ADR was originally committed as `0031`,
> colliding with
> [ADR-0031 (BackendCatalog / DelegationPolicy)](0031-backend-catalog-and-delegation-policy-agent-selection.md),
> which was authored first and is referenced from `ROADMAP.md`, `CONTEXT.md`, and
> three source files. This file took the next free number instead. Its number is
> therefore **not chronological** — [ADR-0034](0034-silero-vad-sole-conformer-in-live-demo.md)
> cites this ADR as prior work despite having a lower number.

`demos/voice_web_server.py` — the server `pnpm dev` actually runs — showed
the same "built but never wired" pattern already found and fixed for
datetime grounding (ADR-0030): `EnsembleEotClassifier`/`LlmEotClassifier`
(ADR-0021), `LlmDualIntentClassifier` (ADR-0015/ADR-0020), and
`ConversationKernel`'s `eot_classifier`/`dual_intent_classifier`/
`speaking_clock` constructor seams all existed, fully unit-tested, and never
constructed by `_build_kernel`. The Kernel always fell through to its
minimal defaults (`EnergyVad`, no `eot_classifier`, `DefaultDualIntentClassifier`,
`SpeakingClock()` with `ms_per_char=0.0`) regardless of whether real Bella
credentials (`API_KEY`) were configured.

User direction: replace `EnergyVad` with Silero VAD; skip porting
`../realtime`'s own semantic-completeness model (FireRedChat) and use this
codebase's existing LLM-backed `EnsembleEotClassifier(LlmEotClassifier(...))`
directly; reuse the existing `LlmDualIntentClassifier` for semantic
interruption; keep every new/changed piece behind a Protocol seam, since
pluggability (Protocol + plugin conformer + Kernel constructor param) is
this framework's explicit original design intent, not incidental structure.
Voiceprint wiring is explicitly deferred to a separate future plan — nothing
downstream reads `TurnContent.voiceprint` yet, so wiring it now would add
surface area for zero visible behavior.

## 1. `Vad` Protocol + `SileroVad` conformer

`EnergyVad` (`server/signals/energy_vad.py`) had no seam — unlike
`AsrEngine`/`TtsEngine`/`LlmClient`, `ConversationKernel` type-hinted
directly against the concrete class. Kernel only ever calls
`process_chunk(pcm16, *, sample_rate_hz) -> Signal | None` and
`measure_chunk(pcm16, *, sample_rate_hz) -> ChunkMeasurement | None` on it,
so a `Vad` Protocol with exactly those two methods, mirroring `AsrEngine`,
was a pure extraction with no Kernel behavior change beyond the type hint.
`EnergyVad` stays the deterministic, no-dependency default conformer.

The onset/hesitation/resume/EoT state machine (`EnergyVad._advance`,
previously) was factored out into a private `_OnsetEotTracker`, so the new
`SileroVad` conformer can reuse the same turn-taking bookkeeping instead of
duplicating a nontrivial 20-line state machine — the two conformers now only
differ in *how* loudness is measured (RMS threshold vs. Pipecat's own
debounced state machine), not in how that measurement becomes a `Signal`.

**Dependency**: `pipecat-ai[silero]` (added to `pyproject.toml`), wrapping
`pipecat.audio.vad.silero.SileroVADAnalyzer` with
`VADParams(start_secs=0.2, stop_secs=0.5, min_volume=0.6)` — the same
defaults `../realtime`'s own Silero wrapper uses. Resolves to
`pipecat-ai==1.7.0` plus ONNX Runtime and its own dependency tree; notably no
PyTorch — the `[silero]` extra is ONNX-only, a lighter footprint than a naive
`torch`-based Silero install would carry.

**Async/sync mismatch (not anticipated going in).** Pipecat's
`VADAnalyzer.analyze_audio(buffer: bytes) -> VADState` is genuinely
`async def` — it offloads ONNX inference to a `ThreadPoolExecutor`
internally (`loop.run_in_executor(...)`), not just for interface
consistency. This framework's `Vad` Protocol, and all three of Kernel's call
sites (`_handle_audio_chunk`, `_handle_audio_during_speak`,
`_handle_audio_during_dual`), are synchronous, mirroring `EnergyVad`.
Two options were considered:

- Make `Vad` async. Rejected: cascades into `EnergyVad` (async-ifying two
  trivial, already-stable sync methods for no benefit to that conformer) and
  into `tests/test_energy_vad.py`/`tests/bench/full_duplex_bench.py`, which
  call `process_chunk`/`measure_chunk` synchronously today — a much larger
  blast radius than the actual problem (one conformer needs to bridge to one
  async library call).
- Reach into Pipecat's private, synchronous `_run_analyzer` directly.
  Rejected: relies on an unsupported, version-fragile internal.

**Chosen**: `SileroVad` stays synchronous-facing; a small `_AsyncBridge`
inside it runs a dedicated background event-loop thread and blocks the
caller via `asyncio.run_coroutine_threadsafe(coro, loop).result()` — paying
the analyzer's own inference latency (~5ms) inline, the same kind of cost
`EnergyVad` already pays for its own cheaper RMS computation. This keeps the
async/sync bridge entirely local to the one conformer that needs it.

`VADAnalyzer.__init__` sets `self._sample_rate = 0` unconditionally
regardless of the constructor's `sample_rate` argument — `set_sample_rate()`
must be called explicitly afterward to actually activate the analyzer's
params (confirmed by introspecting the installed `pipecat-ai==1.7.0`, not
just its docs). `SileroVad.__init__` does this immediately after
construction. `analyze_audio` also accepts arbitrary-length byte buffers and
handles internal frame-window slicing itself, so `SileroVad` does not need
to pre-chunk audio to Silero's native 512-sample window.

**Wiring**: `demos/voice_web_server.py._build_vad()` returns `SileroVad()`,
falling back to `EnergyVad()` with a logged warning on any exception
(`ImportError` or model-init failure). Unlike ASR/TTS/LLM, this is not gated
on `API_KEY` — Silero is a local model, not a Bella call.

**Tests** (`tests/signals/test_silero_vad.py`) run against a fake
`SileroVADAnalyzer` double monkeypatched onto
`pipecat.audio.vad.silero.SileroVADAnalyzer` (scriptable `VADState` sequence)
— no real ONNX model load in CI, following
`tests/speech/test_doubao_asr_session.py`'s fake-double convention.

## 2. Semantic EOT: `EnsembleEotClassifier(LlmEotClassifier(...))`

Pure wiring — both classes already existed and were unit-tested (ADR-0021).
`_build_eot_classifier(llm_client)` returns
`EnsembleEotClassifier(LlmEotClassifier(llm_client))` when `API_KEY` is set,
else `None` (today's punctuation-only EoT behavior, unchanged) — the same
"real backend when credentials exist, else today's default" convention
`_build_asr_engine`/`_build_tts_engine`/`_build_llm_client` already
establish in this file. No new env var. This deliberately does not port
`../realtime`'s own FireRedChat-based semantic-completeness scorer, per
explicit user direction — `EnsembleEotClassifier`'s built-in
`PunctuationEotScorer` fast-path already gives the same fail-open shape for
free, with zero additional vendor dependency.

## 3. Semantic interruption: `SpeakingClock` sizing + `LlmDualIntentClassifier`

`server/signals/speaking_clock.py` defaults to `ms_per_char=0.0` — SYSTEM_EOT
fires immediately once any response is delivered, which makes the DUAL
(barge-in) state unreachable regardless of which `dual_intent_classifier` is
configured. ADR-0007 anticipated exactly this ("deployments that plug in a
real TTS pipeline should size `ms_per_char` ... rather than inherit an
arbitrary default"), but `voice_web_server.py` — which has real streaming
TTS via `DoubaoTtsEngine` — never did.

`_build_kernel` now passes
`speaking_clock=SpeakingClock(SpeakingClockConfig(ms_per_char=_speaking_ms_per_char()))`,
where `_speaking_ms_per_char()` reads `VOICEAGENT_SPEAKING_MS_PER_CHAR`
(default `180.0`) — a rough calibration for a fluent Chinese TTS voice
(~5.5 chars/sec), tunable against Doubao's actual output without a code
change. This is a text-length estimate, not a fix to the deeper limitation:
unlike `../realtime`, which measures barge-in windows from real
audio-frame playback events (Pipecat's `BotStartedSpeakingFrame`/
`BotStoppedSpeakingFrame`), this stays a text-length guess. A true
audio-duration feedback loop would require changing the
`ResponseScheduler`/`StreamingSpokenResponseScheduler` boundary to report
real playback timing back to `ConversationKernel` — out of scope here,
noted as future work.

`_build_dual_intent_classifier(llm_client)` returns
`LlmDualIntentClassifier(llm_client)` when `API_KEY` is set, else
`None` (Kernel's own default, `DefaultDualIntentClassifier`, unchanged) —
same convention as everywhere else in this file.

## Kernel wiring summary

`_build_kernel` builds one `llm_client` via `_build_llm_client()` and reuses
it for `ChatBrain`, `_build_eot_classifier`, and `_build_dual_intent_classifier`
— one real Bella-backed client per session, not three. All new/changed
constructor args (`vad=`, `eot_classifier=`, `speaking_clock=`,
`dual_intent_classifier=`) route through existing Kernel seams; nothing new
was added to `ConversationKernel` itself beyond the `Vad` Protocol type-hint
change.
