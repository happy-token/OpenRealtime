# ADR 0151: Bounded Session input and actual-send recording

Date: 2026-10-07
Status: Accepted for collection and process resource ownership. Session recording query, replay, preservation UI, renderer joins and complete OBS03 acceptance remain open.

## Context

Default recording was approved, with seven-day retention and long-term preservation of marked recordings. ADR0150 established Artifact expiry, pinning and upload ownership. Audio recording must observe accepted input and actual wire output without adding a conversational actor, delaying media on storage, or declaring sent audio to have been heard.

The Endpoint Session can discard or buffer frames while detached and return normally from `send()`. Provider sequence is also not an audio packet counter: model response sequence includes text, and external speech segment index repeats for multiple packets. Recording at generation or assuming a successful method return/continuous wire sequence would produce false output evidence and gaps.

## Decision

`server/realtime/recording.py` contains one bounded recording storage worker per admitted Session. It owns only evidence and storage. Input is captured after payload and input-epoch timeline validation, before `AppendAudio`; its boundary is `validated_input`, not ASR consumption. Duplicate/rejected input is not recorded. Output is captured only after the physical adapter write returns successfully. Its boundary is `transport_send_completed`, not client receipt or device rendering.

The optional `ObservedFrameSender` capability moves the epoch and current-source guard into the Endpoint physical-send lock. It never buffers observed frames. Admission updates the playback clock before the awaited write, so immediate playback receipts retain the existing contract; only successful writes invoke recording. A packet already being written on an old attachment retains that original epoch. Queued packets recheck the attachment, context and delivery permission inside the lock. Text/alignment/terminal frames also use the lock guard, so a revoked reply cannot escape through non-audio frames. Legacy direct Endpoint `send()` buffering behavior remains available to its other callers.

Output WAV positions use the cumulative wire sample clock and original speech/context/epoch. Sent segments test sample continuity, retain actual wire sequence as metadata, and do not interpret repeated/skipped wire sequence as audio loss. Input continuity checks both input sequence and samples. Changes in context, epoch, stream, rate, channels or position split segments; gaps do not insert invented silence.

Defaults: each segment is at most 256 KiB raw PCM, five seconds and 256 frame descriptors; an oversized single frame is explicitly rejected for recording. Each Session owns at most eight queued/active segments, 4 MiB raw PCM including active writes, and 4096 accepted segments. Epoch/speech/stream metadata has 512-byte limits; sequence/time/sample values are exact bounded integers. The process owns at most 64 unsettled recorder instances. Unsupported formats or exhausted budgets stop further capture for that recorder and emit an explicit failure while preserving the voice media path. These are capture limits, not a promise of lossless recording at arbitrary load.

A segment becomes a verified restricted `voice_session_recording` WAV Artifact, with capture-time-plus-seven-day retention. Upload/finalize must preserve the staging Artifact ID, request, size and digest. Only then is an INTERNAL structured manifest plus Artifact reference committed in a separate tenant/user/thread/Session recording Journal scope. Original turn/generation/response correlation remains in its context. Recording manifests never enter model conversation history.

Every manifest explicitly declares `playback_confirmation=not-inferred`. Existing client playback/stop facts remain the authority. The later diagnostic query must join their epoch/speech/sample ranges and distinguish missing, estimated and confirmed playback. This increment does not add an audio API or manufacture a `confirmed_played` track.

## Default composition and lifecycle

The Application Runtime owns `ApplicationRecordingOwner`, its Artifact Store, recorder registrations and expiry maintenance. Memory mode enables recording by default and marks it volatile. PostgreSQL mode selects the existing S3 adapter when all required configuration is present; absent configuration reports `not-configured`, and partial explicit configuration fails before opening resources. There is no silent volatile production substitute. Tests may inject an object client; that is not evidence of real S3 resilience. No migration runs implicitly at startup.

The production Voice Session opens a recorder only after admission and actual conversation opening. Factory/Bridge/initial-frame failures are included in the existing cleanup scope, so engine, admission and event pumps are released. Normal shutdown joins media pumps before recorder flushing.

A three-second write deadline and one-second recorder close deadline bound the caller's wait, not actual IO lifetime. Actual persistence tasks remain owned and may finish later with the original Session identity. Optional observer exceptions are isolated. Until real settlement, purge is rejected and the database pool stays open. Runtime resource close is a shared shielded task; caller cancellation cannot cancel maintenance or poison later close retries. Pending recording/cleanup IO produces `RecordingWritesPending`; a later close can complete after actual exit.

Maintenance waits 60 seconds before its first scan, processes existing ledger batches of 100 and starts no new operation while the previous one remains active. Its actual operation receives a settlement callback at creation and is retained if shutdown begins. It has no independent business actor or alternate cleanup authority. This does not guarantee cleanup completion during a provider outage or after process termination.

## Retention and history deletion

History purge removes the derived recording manifest thread only after the recorder settles. `deleted_recording_threads` counts Journal threads, not WAV bytes. It does **not** claim immediate audio erasure: the existing Artifact contract rejects deletion before the seven-day deadline, and pinned recordings remain retained. Expiry maintenance uses ADR0150's authoritative cleanup ledger. Any policy for early erasure, retention overrides, removal of pinned evidence or a Session preservation button requires a separate explicit contract; this change does not bypass retention.

## Validation and remaining scope

Formal regressions exercise both real Bridge and Voice Session composition, rejected/duplicate input, detached/buffered/failed output, queued epoch/context changes, old attachment writes, actual sample continuity, WAV verification, identity substitution, observer exceptions, budgets, blocked writes, purge reservations, factory failure, close cancellation and blocked cleanup. PostgreSQL tests use isolated randomized schemas and real metadata/Journal transactions with an in-memory object client. They do not call a real provider or migrate production.

OBS03 still needs Session-authoritative manifest pagination, authorized audio access, accurate source completeness/expired states, preservation UI, and confirmed renderer position joins. Full real audio/oracle/provider/load/performance gates G0–G5 and the remaining OBS02 evidence/fault/latency work stay open.
