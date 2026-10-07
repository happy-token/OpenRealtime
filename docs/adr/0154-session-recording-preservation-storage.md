# ADR 0154: Session recording preservation storage

Date: 2026-10-07
Status: Accepted for the storage foundation. Admin API/UI and history purge protection remain open.

## Decision

Preservation is a monotonic policy for the original tenant, owner and Voice Session, not an administrator-owned copy or a pin on only the currently selected segment. An optional `RecordingPreservation` capability records the first operator and mark time. Repeated marks retain these facts. It covers existing eligible AVAILABLE recordings and future recordings from the same Session. It does not revive expired, deleting or deleted artifacts. Eligibility requires the mark strictly before the original retention deadline; equality is already expired.

Memory uses the Artifact Store lock and is volatile. PostgreSQL migration 0038 adds a scoped policy table; each recording create, finalize, preservation mark, delete admission and upload cleanup admission shares a transaction-scoped source lock. No object IO runs under this lock. Marking eligible AVAILABLE rows makes them immutable and cancels expiry intents in the same transaction. Eligible STAGING rows retain their upload revision and permission; successful finalization adopts stronger immutability only after object verification. Failed finalization rearms its expiry cleanup intent. Recorder identity validation permits only the stronger immutable flag after finalization; all other original metadata must still match.

Counts describe metadata state: verified immutable AVAILABLE, eligible pending STAGING and unavailable. A pending count never proves actual upload completion. Upload tasks/attempts still own their unknown IO until real settlement. Cleanup scanning excludes protected pending uploads before applying the batch limit, while source-lock revalidation protects a mark racing with the scan. Revoked, failed and unrelated attempts remain eligible for cleanup. This prevents retained unknown uploads from starving physical orphan cleanup.

Policies expose no unmark operation. Production startup does not apply migrations. Controlled deployment must apply 0038 before using this store version; rollback of preservation obligations requires a reviewed new forward migration. Dropping the policy table automatically would lose obligations. Existing expired audio is not backfilled or restored.

## Validation and limits

Actual memory and isolated PostgreSQL tests cover existing/future segments, restart reconstruction, original scope, first operator/time, exact expiry, held physical uploads, real collector manifests, failed verification and cleanup fairness at batch size one. The fairness regression first failed with a physical orphan left after three scans; it now deletes the orphan while the preserved upload remains pending and later finalizes successfully.

This is an internal storage increment. It does not expose an administrator preservation button or claim protected Session history: HTTP authorization, source resolution under purge races, manifest/diagnostic deletion protection and page integration are the next work. OBS03, renderer joins, real S3/browser playback and the original G0–G5 acceptance remain open. No production database migration, provider request, service restart or remote push was performed.
