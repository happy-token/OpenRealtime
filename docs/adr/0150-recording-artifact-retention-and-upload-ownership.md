# ADR 0150: Recording Artifact retention and actual upload ownership

Date: 2026-10-07
Status: Accepted for the storage prerequisite. Recording collection, runtime composition, maintenance scheduling and OBS03 acceptance remain open.

## Context

The user approved default dual recording, seven-day retention and long-term preservation of marked Sessions. The existing Artifact Store already verifies blobs, enforces tenant/owner access, pins AVAILABLE objects and keeps PostgreSQL upload/cleanup ledgers. Its retention_until only prevents early deletion: voice recording objects previously acquired no expiry cleanup intent. Simply adding an expiry sweep exposed upload/delete races, including SDK threads that continue after caller cancellation.

This decision completes a storage prerequisite. It does not claim the microphone/egress recorder, renderer mapping, audio API or default recording policy has been wired. The actual recording consumer must choose seven days at capture and register authoritative input/sent/playback provenance separately.

## Decision and module boundary

Reuse the existing Artifact Store and its durable cleanup ledger. A `voice_session_recording` request requires an aware retention_until. PostgreSQL creates its expiry intent atomically with the Artifact row; replay does not revive cancelled/completed intents. Memory scans only expired, unpinned recording records and reuses the existing delete phases. Other Artifact kinds do not gain recording expiry semantics. Existing avatar orphan cleanup keeps its grace policy.

An optional ArtifactCleanup protocol exposes the already existing reconcile_cleanup_ledger operation without making all third-party ArtifactStore implementations implement maintenance. Strict batch size is integer 1–1000, excluding bool. Each invocation separately bounds upload-attempt and Artifact candidates; it is not a total execution-time deadline, and memory selection scans its in-process metadata. Artifact candidate retries prefer fewer previous attempts; failed Memory orphan keys move to the end of the pending map, so a permanent first failure does not starve a different eligible recording or orphan. This does not promise global or distributed scheduling fairness.

The only additional implementation module is the private ArtifactUploadOwner shared by both Store conformers. It owns up to 64 actual upload tasks, creates no worker queue/state actor, and shields those tasks from a waiting caller's cancellation. Capacity remains occupied until the real coroutine completes, including its boto3 to_thread await, metadata binding and orphan cleanup. Done callbacks release ownership and retrieve late exceptions. A caller's cancellation is not a rollback of an accepted storage operation. Cancellation cannot stop a native SDK worker or retract its completed put; it also cannot make that worker disappear from ownership.

Memory records active uploads and pending orphan keys inside the existing Store. Delete revokes publication by entering DELETING but cannot claim DELETED while active/pending uploads exist. A late rejected put retains orphan retry ownership if object deletion fails. Maintenance cleans confirmed orphan IO before finalizing Artifact deletion. Failed finalize performs revision and STAGING checks even on its failed-integrity branch, so it cannot revive a deleted object. A pin winning after candidate selection does not become an erroneous storage failure. These are in-memory guarantees only; no process-crash durability is claimed.

## PostgreSQL unknown writes and completion

Forward migration0036 adds put_completed=false to the existing artifact_upload_attempts table. It does not replace deployed migrations or create another ledger. On actual put return, one SQL statement records completion before the crash hook or receipt CAS. Original pending admission is preserved; a cleanup-revoked attempt remains revoked, moves to cleanup_pending and clears the old cleanup token. It cannot regain publication rights.

An object delete before put completion is not proof that a future write cannot occur. If completion is unknown, a cleaner retains cleanup_pending, an explicit unknown reason and a bounded subsequent check time instead of marking cleaned. If put subsequently returns, the existing attempt is rearmed for cleanup. If a process crashes between physical write and recording completion, the durable unknown attempt still causes later deletion attempts. Unknown attempts may need repeated maintenance indefinitely; this decision does not invent a force-stop acknowledgement for the provider, and does not claim unresolved metadata has been fully reclaimed.

Only a completed put plus successful object deletion under the current cleanup token can mark cleaned. If the terminal UPDATE affects zero rows because another owner revoked its token, reconciliation reports no success. Deletion failure retains retry information across Store reconstruction. Existing Artifact revision CAS serializes pin and delete claim: pin before claim preserves the object; pin after DELETING is rejected explicitly. Pin cancels the expiry intent in the same PostgreSQL transaction.

Previously terminal legacy cleaned rows cannot prove whether an older external write remained pending. Migration0036 does not invent that missing history or automatically reopen arbitrary old rows; deployment must separately assess legacy orphan inventory if applicable. Existing committed attempts are outside cleanup selection.

## Deployment and verification

Execute0036 through the controlled migration utility before deploying a Store using put_completed; no service startup or this task automatically migrates production. PostgreSQL16 adds the constant-default column without a table rewrite, though ALTER TABLE still acquires a schema lock and belongs in the migration window. Runtime task ownership is process-local; the durable PG ledger supplies unknown-write cleanup across process failure.

Formal controlled tests cover seven-day expiry, unrelated artifacts, marked retention, pin-before/after delete, retries across reconstructed Stores, late put before physical write, orphan-delete failure, completion-before-crash ordering, stale cleanup token, SDK thread cancellation and all64 owned tasks retaining capacity. Fake clocks model expiry; actual local PostgreSQL and the production boto3 adapter with an injected local synchronous SDK exercise persistence/worker seams. They do not benchmark live S3, voice latency or real acoustic playback.

The recording consumer, bounded segment/media bytes, authoritative Session scope, input/sent timelines, confirmed renderer ranges, runtime Store lifetime/draining, maintenance scheduling, read-only audio references and user-facing expired/failed states remain the next OBS03 tasks. No business reply module or default feature switch is introduced here; G0–G5 and the rest of OBS02/OBS03 remain open.
