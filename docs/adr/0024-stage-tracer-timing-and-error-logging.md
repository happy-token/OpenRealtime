---
status: accepted
---

# StageTracer: per-call timing/error/timeout logging

Before this ADR, `voiceagent/` had zero timing instrumentation anywhere
(confirmed via grep: no `time.time()`/`perf_counter()` hits) and error
handling only existed at a handful of seams (`ConversationKernel`'s
`brain_error` catch, `EnsembleEotClassifier`'s fail-open, `HookPoint`'s
veto-on-raise) — none of which recorded how long the failing call had been
running before it failed. Two real ASR conformers made this worse:
`DoubaoAsrSession` had no logger at all, and `BellaAsrSession` silently
swallowed `ConnectionClosed` in its read loop. Diagnosing a slow or failing
turn meant adding prints and reproducing — untenable once this runs anywhere
but a developer's terminal.

`realtime` sibling reference project (referred to elsewhere in this
codebase as `../realtime`) already solves this with
`server/observability/tracer.py`'s `SessionTracer`/`Span`: an async
context manager that always records `duration_ms` + `status` (ok/error/
cancelled) on exit and never swallows the exception it observed, correlated
by ids that thread through every log line.

## What was ported, and what wasn't

Only the *shape* was ported — a span wraps one call, always logs
duration+status on exit, re-raises whatever it caught — as
`voiceagent/observability/tracing.py`'s `StageTracer`/`Span`/`SpanStatus`.
Three things were deliberately left behind:

- **loguru.** Realtime uses it; this project has zero third-party logging
  dependencies (`pyproject.toml` lists only `pydantic`/`websockets`), and
  stdlib `logging` already covers every requirement here (level-based
  routing, `exc_info` for tracebacks, per-module loggers).
- **A new turn/session/generation-id triple.** Realtime correlates spans
  with three separate ids it mints itself. This project already has a
  session id (`InMemoryEndpointSession.session_id`, threaded through
  `EventLedger.emit`) and, more importantly, an existing per-turn
  `generation: int` (`core/generation.py`'s `GenerationCounter`/
  `GenerationLease`) that every kernel method already receives or can reach.
  Reusing `generation` for span correlation means no new id concept for a
  reader to learn, and `stage=... session=... generation=...` lines are
  already greppable against every other log line the kernel emits.
- **In-process aggregation (p50/p95/etc).** Per explicit decision, this ADR
  covers per-call detailed logging only. Log lines are meant to be searched
  post-hoc by `session`/`generation` when troubleshooting a specific turn,
  not summarized into percentiles in-process — that's a job for whatever
  external log/metrics pipeline ingests these lines, not this library.

## Where spans are (and aren't) placed

`StageTracer.span()` wraps one call inside an *existing* seam and is placed
at every per-turn/per-session call site: Brain routing, EoT classification,
Turn Policy evaluation, voiceprint match, response delivery (text+TTS, at
the single `ResponseScheduler.deliver` call site so `Immediate`/`Spoken`/
`StreamingSpoken` schedulers and TTS are all covered without touching those
files), delegation await, and ASR session start. `HookPoint.apply` — a sync
call site — uses `sync_span()` instead, `StageTracer`'s log-only sync
counterpart (no ledger emit: `EventLedger.emit` is async, and there is no
loop-safe way to fire-and-forget it from a sync context without risking an
orphan task).

Deliberately **not** spanned: `push_audio`, `add_audio`, and VAD chunk
processing. These run once per audio chunk (tens of times a second); spanning
them would flood the log with lines no troubleshooting session would ever
want to grep through. Latency at that granularity, if ever needed, is a
different, sampling-based instrument — not this one.

## Module-local fixes a kernel-level span can't cover

A span around `EnsembleEotClassifier.classify()` as a whole only sees
ensemble-level latency — it can't tell you *which* scorer failed. So
`ensemble_eot_classifier.py` gained its own local timing + `logger.warning`
before falling back to the fast scorer. Likewise `DoubaoAsrSession`/
`BellaAsrSession`'s read loops gained session-duration logging on
`ConnectionClosed` and unexpected exceptions (previously silently swallowed
or absent entirely), and `OpenAiCompatibleLlmClient._stream_sync` gained
local timing that distinguishes a `TimeoutError` from other `URLError`s
before re-raising — the one HTTP call whose own network latency, as opposed
to kernel-level routing overhead, matters most when troubleshooting a slow
reply. None of these log the API key or request/response bodies.

## Ledger integration

When constructed with an `EventLedger` and a non-`None` `generation`,
`StageTracer.span()` also emits a `stage_span` ledger event
(`name`/`status`/`duration_ms`/`error`/tags) after logging. Existing
Observers — e.g. `examples/voice_web_server.py`'s `_log_ledger_event` — see
span data for free, with no new subscription wiring.
