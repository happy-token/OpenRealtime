# ADR 0155: Session preservation source and history protection

Date: 2026-10-07
Status: Accepted for internal Runtime operations. Authorized HTTP and UI remain open.

## Decision

Consume ADR0154 through `ApplicationRuntime.preserve_session_recordings`. Resolve original tenant, user and thread using the bounded authoritative recording Journal query; if no recording exists, use the authoritative dialogue page. Unknown or ambiguous sources fail. Never synthesize ownership from an administrator, telemetry or a requested Session ID. Recheck the same source after entering the mark/purge coordinator. A purge that wins before the mark invalidates its source and the late mark fails instead of creating a phantom preservation policy.

PostgreSQL uses the existing source advisory lock in one transaction. History purge acquires all selected source locks in sorted order, checks preservation before any destructive statement and rechecks Journal identity. Its policy check covers the selected Session IDs because diagnostics deletion uses that scope. One preserved Session rejects the entire batch before changes. A persistent mark protects recording manifests, input evidence, dialogue history, stop facts and diagnostics even when object storage is absent after restart. Missing schema/errors fail the operation; startup does not apply migration 0038.

Memory exposes an optional shared history coordinator on its Artifact Store. Runtime mark and purge operations using the same volatile store serialize source revalidation and policy checks across Runtime instances. The coordinator owns metadata/history work only, not physical object IO; the existing Artifact lifecycle lock remains separate. Low-level Artifact preservation is still an internal storage capability, not the full Journal authorization/coordination entry point. Callers seeking Session history preservation must use Runtime.

Mark operations use the existing eight actual recording operation slots and four-second caller deadline. Timeout/cancellation does not cancel or release the actual mark, its transaction or resources. The actual task callback settles ownership; history purge and shutdown remain blocked while it is unresolved. A retry is idempotent and retains the first mark facts. Returned metadata counts do not prove physical pending uploads completed.

Only a preservation conflict while entering a deletion guard becomes `SessionHistoryDeletionConflict`. Exceptions from the enclosed mark or purge keep their original meaning. A failed mark must not be described as a successfully preserved Session.

## Structure and verification

No new actor, queue or recovery state machine. Composition stays in Runtime, task lifetime and volatile guard adaptation in ApplicationRecordingOwner, source verification in SessionRecordingReader, and durable policy/locks in the existing PostgreSQL preservation helper.

Regressions use actual Runtime/Journal/Artifact paths: original source without administrator fallback; mark before first recording and later verified segments; batch rejection before mutation; unknown source; Memory mark/purge winners across two runtimes; timeout retaining actual ownership; PG mark/purge winners across two pools; restart protection with no object client. The original unprotected purge test failed by deleting a preserved Session and now passes. A reviewer identified a guard error translation issue; a formal red test reproduced it and the entry-only translation now passes.

This increment does not add an HTTP write route, Agent write permission or page button. Catalog preservation state, public administrator gate, same-theme UI and actual deployment/browser playback remain next work. OBS02/OBS03 and all original G0–G5 acceptance remain open.
