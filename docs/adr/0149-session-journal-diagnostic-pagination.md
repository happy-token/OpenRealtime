# ADR 0149: Session Journal queries and diagnostic pagination

Date: 2026-10-07
Status: Accepted for implementation; deployment and complete OBS02 evidence acceptance remain open.

## Problem

ADR0148 deliberately fails closed when a conversation thread exceeds 1000 items or telemetry's identity page has a continuation. That prevents cross-Session disclosure, but cannot provide complete conversation evidence for long or continued Sessions. Pagination must query original Session ownership, not generation or a shared thread's first page. Input evidence may legitimately have the same Session ID in another Journal thread and must not masquerade as a second conversation identity.

## Decision

Add an optional `SessionConversationQuery` contract inside the existing Conversation Journal Seam, with `read_session_page(voice_session_id, after_sequence, limit)` and immutable `SessionConversationPage(items, next_sequence)`. Only original `USER_INPUT`/`ASSISTANT_OUTPUT` items participate in this conversation view. Their tenant/user/thread identities must be unique for this Session; multiple identities fail as ambiguous. Non-dialogue evidence/summary/tool records do not establish conversation scope. This is a diagnostic view, not model projection or a new state controller.

The in-memory conformer maintains references indexed by Session and conversation scope, under its existing lock. Duplicate append does not duplicate the index; both thread deletion operations remove it. Within the sole scope, thread sequences are monotonic, so keyset paging uses bisect and copies only the requested page. It does not scan unrelated Sessions or copy an entire thread. The storage remains non-durable.

PostgreSQL uses original `voice_session_id`, the two kinds, and exact resolved tenant/user/thread. A single SQL statement computes at most two distinct scopes and, only for exactly one scope, reads `limit + 1` items in sequence order. Scope proof and content have one statement snapshot, including inside the caller's existing transaction. No forced nested isolation change is introduced. Work is indexed to this Session and bounded in time, not claimed to be constant-cost: proving one scope may traverse this Session's entries. The query uses the smaller of the current nonzero statement timeout and 3000ms, restores the prior value on success, and rolls back local changes on failure. The operation has a 4s coroutine deadline; the private HTTP RPC still has its existing 5s observer bound. These bounds do not claim to force-kill an arbitrary custom Journal plugin.

Migration0035 adds a partial `(voice_session_id, tenant_id, user_id, thread_id, sequence)` index for the two kinds with `CREATE INDEX CONCURRENTLY`. It must run outside a transaction block; the existing controlled `apply_migrations` runs individual statements without implicit production startup migration. It now verifies that the expected index is ready/valid and attached to the expected table with the expected keys. A leftover invalid or incompatible same-name index fails explicitly instead of letting `IF NOT EXISTS` imply success. No stored rows are backfilled or rewritten. Controlled rollback is `DROP INDEX CONCURRENTLY` of this index; after diagnosing a failed build, drop/rebuild it before rerunning migration. Do not edit earlier deployed migrations.

## HTTP, Agent and UI contract

The private Control Plane adds `GET /observability/sessions/{id}/conversation-page?after_sequence=0&limit=200`. The production application assembly binds the existing Journal query via the CLI callback seam. The response is `{voice_session_id, items, next_cursor}`. Each projected row carries original Session ID and decimal-string `journal_sequence`; next cursor is the last scanned page sequence, including any non-text item omitted by presentation. Cursor is a nonnegative signed bigint, page size is 1–1000; malformed/duplicate query values fail before invocation. Missing implementations do not silently fall back to thread replay.

The unified diagnostics GET now reads this page endpoint for both administrators and restricted Agents. It accepts an independent decimal-string `conversation_cursor` and returns `conversation_next_cursor`, preserving existing schema_version1, conversation array and other source cursors. It requests 200 items and validates page size, Session provenance, row shape, monotonically advancing sequences and a progressing next cursor. Invalid pages become an unavailable source while useful other sources remain. Bigints remain strings rather than losing precision in JavaScript. The old internal array endpoint remains for legacy callers with ADR0148's conservative limits; it is no longer the unified interface's conversation source.

The real detail page's existing “加载更多日志” advances any of the three cursors. Merge by `item_id` or `event_id`, updating only requested sources. Refresh, Session switch and unmount cancel/fence the old paging request; a supplier ignoring AbortSignal cannot publish old data or errors. Duplicate clicks share one pending request, with a 15s caller deadline. Agent credential files describe the third cursor. Paging retries do not discard previous accepted rows or claim complete collection when sources are missing.

## Evidence and limits

Regression cases cover Session continuation behind more than 1000 other rows, repeated generation, exact scope/kind isolation, ambiguous identities, deletion/idempotence, bigint boundaries, real HTTP→production reader→Journal paging, malformed/regressive upstream pages, independent UI merge and stale Session responses. Isolated PostgreSQL schemas verify true database results, expected index plans, idempotent migration, external transaction compatibility/timeout preservation and a failed concurrent index build followed by explicit refusal and controlled repair.

No user services are restarted, no production migrations/credentials are changed and no provider requests are made. Real administrator/browser and external Agent deployment calls still need acceptance. This closes the code gap for long-Session conversation paging; input-evidence API aggregation, dual recording/artifact access, full error/connection completeness, production-scale performance and G0–G5 experiments remain open.

A successful HTTP response can contain a failed source. The UI retains that source's existing records and retry cursor, advances successful requested sources, and shows partial failure. Failed-source status is retained in the report; it never becomes an empty, complete source by merging.
