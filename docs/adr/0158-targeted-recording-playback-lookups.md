# ADR 0158: Target recording playback receipts by original attachment

Date: 2026-10-07
Status: Accepted for the local targeted positive-evidence lookup increment.

## Problem and decision

ADR0157's initial one-page diagnostic projection cannot find exact receipts after 5000 unrelated events. Formal actual Runtime tests reproduce both Memory and PostgreSQL as unknown instead of reported, and a Memory no-general-scan test reproduces unavailable. The requested Session diagnostic workflow needs positive receipt evidence for each recording page independent of general telemetry pagination.

Add an optional receipt lookup capability to the existing telemetry seam, accepting at most200 original recording attachment keys and returning at most one maximal coherent exact prefix per key. Keys retain all ten identity/clock fields from ADR0157, including null turn/response. The recording reader uses this capability when available inside the same actual IO owner/deadline. Old adapters keep the explicitly truncated one-page fallback; production Memory and PG use targeted lookup.

Memory updates a derived maximal-prefix dictionary during append and removes affected keys on Session deletion; reads do not scan general telemetry or receipts. PostgreSQL reads existing immutable records through a concurrent partial expression index. An immutable validated sample-position function rejects malformed/estimated/incoherent receipts without unsafe casts; an attachment digest is solely an index aid, while the actual query independently checks every original identity field. Limit one result per requested attachment in a single snapshot and apply both SQL and operation deadlines. No new table, actor, queue, business permission or recovery state.

Both immutable functions fix their search path to `pg_catalog`. Index validation runs within its own SAVEPOINT with a normalized search path and explicitly restores caller settings after success. It checks the correct table, exact expression/predicate, dependent function OIDs, readiness/validity, descending position and non-unique/non-exclusion contract. Wrong or missing indexes fail only optional playback evidence; audio remains readable. Controlled migrations0039/0040 run explicitly in order, with the concurrent index outside a transaction; never change immutable function semantics in place after building this index.

The adapter's returned keys undergo the same strict validation as requested keys before membership comparison; Python's bool/float equality with integers must not fabricate exact attachments. A successful target query eliminates general-page truncation for these requested attachment prefixes, but cannot prove event collection completeness. Memory's derived dictionary grows with distinct valid attachments and is cleared by Session deletion; this does not impose a total historical store or process-memory bound.

The receipt prefix is positive evidence only. Successful indexed lookup, missing rows or healthy collection do not prove complete audio evidence, physical speaker output or absence of playback. Existing public count whitelist, source health, `playback_confirmation=not-inferred`, same-theme UI and exact Session Agent/admin authorization remain unchanged.

## Implementation and acceptance

1. Actual Memory/PG red-to-green >5000-events and no-general-scan catalog regressions.
2. Shared strict key validation and unchanged malformed/legacy/foreign/zero/max-prefix semantics; Memory append/deletion/reingestion regressions.
3. Controlled forward-only function/index migrations and fail-closed validation; real PG long Session, malformed JSON, rounding, nullable identity, timeout restoration, index plan and restart tests.
4. Same owned optional query limits/cancellation/late resources; production-reader capability and fallback regressions, full relevant and whole test suites, independent reviews.
5. Update reports/requirements/plan without closing OBS02/03 or original G0–G5. No production migration, user-service restart, real S3/provider call or push.

## Acceptance evidence

Local steps1–5 have been verified. Real Memory and PG >5000-event catalog regressions and Memory no-general-scan regression first failed, then passed. Returned bool/float keys, search-path-visible valid indexes, shadowed immutable builtins and wrong UNIQUE index each have formal red-to-green regressions. SQL and Python sample validation agree on malformed types, ties-to-even and large safe clocks; nullable scope, all ten identity dimensions, deletion/reingestion, maximum prefix, late IO, caller timeout restoration and wrong index cases pass. Real `EXPLAIN ANALYZE` selects the partial attachment index for the long-session fixture.

Final scope and validation: [implementation report](../reports/2026-10-07-targeted-playback-receipt-lookups.md). Original renderer/device, collection completeness, deployment/S3/provider and all original OBS02/03/G0–G5 acceptance remain open.
