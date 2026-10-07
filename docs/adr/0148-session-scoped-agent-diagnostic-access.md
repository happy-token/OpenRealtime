# ADR 0148: Session-scoped Agent diagnostic read access

Date: 2026-10-07
Status: Accepted for implementation; deployment and complete OBS02 evidence acceptance remain open.

## Context

OBS02 requires an Agent to investigate one Session ID without sharing an administrator's browser cookie. The existing diagnostics GET aggregates telemetry, conversation and debug logs, preserves independent cursors, and marks incomplete sources. It currently authenticates only through the application's administrator identity. This decision concerns delegated read access, not reply coordination or recording storage.

## Decision

Reuse the existing diagnostics GET. An application administrator delegates a named, independent machine identity through same-origin `POST /api/observability/sessions/{sessionId}/diagnostics/access?agent_id=diagnostic-agent`. The server signs an exact-Session, read-only grant using an independent server-only `OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET` of at least 32 non-whitespace characters. Empty/weak configuration disables signing and machine verification. Configuration must use randomly generated material, distinct from login/provider secrets.

The grant expires 15 minutes after issuance, has version, fixed audience and scope, named subject, exact Session ID, issued/expiry timestamps and random nonce. HMAC SHA-256 protects these claims. Verification has bounded token/identity length, fixed signature length, constant-time signature comparison and absolute time checks. A credential cannot select wildcard Sessions, mutate data, mint another credential, or use account-management/list/overview routes. Those routes retain their existing administrator checks. A presented invalid Authorization header is rejected without browser-cookie fallback. No Authorization header preserves the existing application-admin path.

Admin POST requires application-admin authentication and a matching Origin header before issuance. It does not accept machine identity as admin authority. Grant issuance is a delegation of admin access to the specified ID; it does not establish that a Session exists. GET establishes source availability through the existing query path. This first implementation does not persist grants or require a DB migration.

Machine GET queries only the authorized Session's three sources and preserves both pagination cursors and source completeness. It neither forwards the bearer to the private Control Plane nor returns global collection health, which is outside this grant. `collection_health: null` is explicit; machine callers cannot infer global collection health from their Session. Recording remains truthfully `not-configured`. Credential responses and diagnostic content use `Cache-Control: no-store`; bearer transport is the Authorization header only. No token is placed in the endpoint URL, operational logs, localStorage or ordinary diagnostic JSON export.

The Conversation Journal is thread-scoped; several Voice Sessions can share that thread. The production per-Session reader flushes telemetry and reuses `session_history_scope` to resolve the recorded tenant/user/thread, then filters by each item's original `context.voice_session_id`. It returns that identity in each projected row; generation is not an authorization key. Legacy local lookup without metadata still applies exact original Session filtering. Ambiguous recorded identities fail. The existing array API scans at most 1000 thread items and probes one additional item: if more exist, the source fails as unavailable rather than returning a falsely complete prefix or silently missing a later continued Session. This intentionally bounds work; a paginated conversation API is still unfinished.

This caller sets the existing resolver's optional `require_complete=True`: a telemetry page with `next_cursor` cannot prove unique identity and fails as unavailable, rather than silently choosing the first 5000 events or scanning without bounds. Other existing history/deletion callers keep the default behavior. A bounded dedicated Session identity authority is a remaining improvement for large Sessions; the conservative refusal does not mean their conversations are empty.

The machine aggregation boundary separately verifies telemetry summary/events, debug timeline/entries and every conversation row against the grant's Session ID. A mismatch or missing provenance invalidates the entire source while useful other sources remain available. An older running backend without conversation-row provenance can therefore return `conversation: unavailable` to the Agent, never silently expose the old whole-thread view. Administrator-only legacy source shapes remain readable during deployment; the updated production reader itself is per-Session for both consumers.

The real Session detail page provides a **生成 Agent 只读凭据** button. It downloads a separate credential JSON containing the exact endpoint, Authorization value, expiry and pagination instructions. The user gives this sensitive short-lived file to the investigating Agent. Demo pages disable issuance. Credential generation has a bounded request, duplicate-click protection and unmount/session cancellation. The ordinary diagnosis export does not contain credentials.

## Revocation and operational limits

Expiry is absolute, not sliding. The Agent cannot renew itself; an admin must explicitly delegate again. Rotating the independent secret revokes all outstanding grants. Removing an admin grant does not immediately revoke an already issued read grant; its maximum remaining lifetime is 15 minutes. Per-grant early revocation and a durable issuance/use audit are separate remaining operational requirements if requested; this implementation makes no claim that those exist. Production traffic and credential files must use an approved secure channel/HTTPS. A Session ID alone is never authentication.

The capability authorizes access for its holder; `agent_id` is an admin-assigned diagnostic subject, not proof of an external workload's identity. The private Control Plane remains private. No new business state machine, queue, controller, recording subsystem or provider request is introduced.

## Verification and acceptance

Tests cover signed identity, exact Session, absolute expiry/future issuance, rotation, tampering/oversize/malformed headers, wrong scope/audience, disabled configuration, admin/Origin enforcement, machine-only denial of issuance, unavailable admin services, independent paginated retrieval, no cross-Session/global health query, no credential forwarding or report echo, and disabled demo issuance. The accepted code must also receive independent review and TypeScript/lint checks.

Deploy-time secret setup, actual administrator button/download and external Agent HTTPS calls remain release acceptance. This does not complete OBS02 recording/evidence completeness, OBS03 dual recording, or G0–G5 runtime/real-provider experiments.

## Follow-up: ADR0149

The conversation query and pagination limitations above describe the initial implementation and the retained legacy `/conversation` reader. [ADR0149](0149-session-journal-diagnostic-pagination.md) replaces the unified diagnostics GET conversation source with a Journal-authoritative, exact-Session paginated query, including a third independent conversation cursor. Legacy conservative refusal remains for old callers. Access claims, absolute expiry and revocation limits are unchanged.
