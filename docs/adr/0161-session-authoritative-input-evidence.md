# ADR 0161: Read input evidence from original Session Journal identity

Date: 2026-10-07
Status: Accepted for the bounded local closeout; production deployment remains separate.

## Problem

The existing input-evidence reader resolves scope from the telemetry first page, falling back to configured local identity. It cannot prove the complete original identity for long sessions, after telemetry loss, or when a continued thread belongs to another owner. The unified Agent endpoint also does not include input evidence. Before aggregating that source, its reader must use authoritative Journal identity rather than guessed metadata.

## Decision

Add an optional Session input-evidence query contract to the existing Journal Seam. Memory maintains an append/delete index; PostgreSQL uses a producer-specific concurrent partial index and one bounded snapshot query. Resolve at most two original evidence and dialogue scopes, reject ambiguity or mismatched source thread, filter exact original Session and retain sequence ordering. No new table, worker, actor or state machine. Reuse the existing evidence content and writer; pagination remains independent of telemetry and dialogue. Export exact bigint cursors as strings and explicit volatile/durable status. A malformed committed evidence envelope is unavailable rather than silently discarded.

The authority, private HTTP, unified Agent response and themed administrator input-evidence tab are implemented. Four sources paginate independently; failed sources retain their records and cursors. `collected` comes from the original scope in the same Memory lock or PostgreSQL snapshot, distinguishing an actual collected empty tail from an unknown Session with a supplied cursor. Exact bigint sequences remain strings. Available input evidence alone can return HTTP200.

Actual recorder/Journal, identity ambiguity, no-telemetry HTTP, real isolated PostgreSQL and Chrome administrator/no-Cookie Agent regressions pass. The browser also exposed the Agent mint route's normalized-localhost origin defect; it now shares the existing strict HTTP-authority check with recording preservation, retaining cross-origin and Agent-write rejection. See the [closeout report](../reports/2026-10-07-voice-closeout.md).

Migration0041 ran only in owned test schemas. Production deployment requires the index and both updated services. This closes the user-authorized local input-evidence increment, not the original complete OBS02/03 or G0–G5 provider/device/deployment experiment gates. The old continuous goal is paused.
