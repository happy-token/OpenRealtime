# ADR 0152: Session-authoritative recording queries and owned reads

Date: 2026-10-07
Status: Accepted for storage/query access. HTTP, public authorization and replay UI are subsequent integration; complete OBS03 remains open.

## Decision

Add optional `SessionRecordingQuery` to the existing Journal seam. Resolve the unique recording scope from original Session evidence, verify its derived recording thread and compare any original dialogue scope. Conflicting identities fail closed. Admin identity and telemetry pages never supply Artifact ownership. Memory indexes and PostgreSQL one-snapshot queries support independent decimal-sequence pagination and exact Artifact lookup; duplicate references across items are ambiguous. Producer-only indexing deliberately includes malformed manifests so they cannot silently disappear.

Controlled migration 0037 adds a concurrent partial recording index. Migration verification checks ready/valid state, table, ordered columns and canonical partial predicate for both 0035 and 0037. A matching name with an incompatible predicate is refused, never repaired automatically. Valid reserved schema names are quoted. No production startup migration is introduced.

`SessionRecordingReader` validates exactly one manifest and one Artifact reference, internal visibility, original context/Session, capture boundary, seven-day policy, sample/frame continuity, size and digest. It derives Artifact access from that evidence and checks original owner, source, restricted classification, phase and retention metadata. Metadata queries use at most four fixed workers per actual read, joined before releasing that read even on errors; original page order is preserved. Catalog status distinguishes available metadata, expired, deleted and unavailable; availability is not a claim that the physical object has been fetched. Audio reads verify bytes/hash/PCM WAV parameters and recheck original Journal authority and retention after IO. Sent recordings remain `playback_confirmation=not-inferred`.

Application ownership retains at most eight actual read Tasks. Four seconds bounds caller wait only. Cancellation/timeouts do not cancel or release an actual store read; settlement callbacks retrieve late errors and release capacity. Pending reads prevent Session purge and pool shutdown, including after a caller has returned. A retry may finish resource close after actual IO exits. This is process ownership, not forceful termination of a noncooperative SDK or durable survival of a process crash.

## Evidence and limits

Formal tests cover unique scope, pagination, conflict, duplicate Artifact references, both deletion paths, scope isolation, expiry, pinning, integrity metadata and post-IO revocation/expiry. Eight cancelled callers retain real read capacity until exit. Real local PostgreSQL tests use randomized schemas, verify pagination/lookup/deletion, nested 100ms timeout restoration and refusal of incorrect index predicates; schemas are removed afterward. Object clients remain in memory; production migrations and real S3 are not verified. The legacy object client loads a complete blob before verification: the response limit is not a hard SDK peak-memory limit for a corrupt oversized object.

Next integration: private runtime HTTP readers, admin/exact-Session Agent public authorization, bounded verified audio responses and replay UI. Preservation controls and confirmed renderer epoch/speech/sample joins remain open. OBS02 and original G0–G5 acceptance remain open.
