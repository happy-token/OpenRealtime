---
status: accepted
---

# Make a server-owned Conversation Journal the authoritative history

**Storage decision — ADR-0055:** PostgreSQL is the only production durable
conformer for Conversation Journal and related authoritative metadata. In-memory
remains test-only. Large media/artifacts live behind an S3-compatible Artifact
Store and Journal retains opaque Artifact References. SQLite is not a production
or migration-stage target.

**Implemented foundation:** typed immutable Journal items, content digests,
globally unique item IDs, idempotent append/conflict detection, per-thread
server sequence/CAS, scoped reads, and model projections now have matching
in-memory and PostgreSQL conformers. Delegation request, waiting, failure, and
terminal-result facts are committed through the same Unit of Work as task and
Outbox state. The live Pipeline Conversation Engine path now commits each
accepted user turn before provider dispatch and appends one coalesced assistant
item at completion, cancellation, or failure; token/audio deltas remain outside
the Journal as required below.

OpenRealtime will maintain one server-owned Conversation Journal per persistent thread. It is the only authoritative semantic conversation history. OpenAI Realtime conversations, Doubao sessions, Pipeline prompts, and external Agent histories are provider-specific Conversation Projections that can be discarded and rebuilt from the Journal.

This is required for genuine Engine replacement, reconnect continuity, multi-Agent delegation, and deterministic tool/confirmation recovery. A provider session cannot be the source of truth because it has provider-specific item types, finite lifetime, context-window behavior, retention policy, and failure semantics. Event Ledger also cannot fill this role: it is an operational observer fan-out, not a durable semantic store or ordering authority.

## Ownership boundaries

| State | Authority | Purpose |
|---|---|---|
| Semantic conversation history | Conversation Journal | Restore and project user, assistant, tool, delegation, and confirmation context |
| Live session lifecycle/dialogue state | Conversation Kernel | Order the current Voice Session and enforce Generation |
| Active tool/task/confirmation state | Work Registry and task backends | Execute and supervise in-flight work |
| Provider/model context | Conversation Projection | Supply a bounded provider-specific view |
| Logs, metrics, traces | Event Ledger and observability sinks | Diagnose and measure runtime behavior |
| Physical connection continuity | Endpoint Session | Detach and reattach transport connections |

Conversation Journal records important lifecycle facts about work, but it does not execute work or replace Work Registry. Event Ledger may observe every Journal append, but observing an append is not what makes the append authoritative.

## Journal protocol

Conceptually, the persistence Seam provides:

```python
class ConversationJournal(Protocol):
    async def append(
        self,
        item: ConversationItem,
        *,
        expected_thread_version: int | None = None,
    ) -> AppendResult: ...

    async def read(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[ConversationItem, ...]: ...
```

The exact storage API may evolve, but these invariants are fixed:

1. the server assigns a monotonic sequence within each `thread_id`;
2. `item_id` is globally unique and provides idempotent append semantics;
3. retrying the same `item_id` with identical content returns the existing result;
4. reusing an `item_id` with different content is a conflict, never an overwrite;
5. accepted records are append-only; correction, redaction, supersession, or erasure is represented explicitly according to retention policy;
6. reads return a deterministic canonical order;
7. schemas are versioned and unknown future versions fail explicitly or are preserved opaquely—never silently reinterpreted;
8. tenant/user authorization is checked before both append and read.

An in-memory conformer is acceptable for tests and local demos. Production startup must select a durable conformer or explicitly declare an ephemeral session policy; it must not silently fall back to volatile storage after a persistence failure.

## Canonical Conversation Item

Every item contains at least:

- `item_id`, `schema_version`, `thread_id`, and server-assigned `sequence`;
- `tenant_id`, `user_id`, `voice_session_id`, and `turn_id` when applicable;
- item kind and typed content parts;
- creation timestamp and producer identity;
- causal references such as `parent_item_id`, `response_id`, `call_id`, `worker_id`, or `confirmation_id`;
- visibility/audience rules;
- lifecycle status such as committed, completed, failed, cancelled, superseded, or redacted;
- optional provider correlation kept as namespaced metadata, never canonical identity.

Initial semantic item families are:

| Family | Examples | Journal behavior |
|---|---|---|
| Session | voice session opened, resumed, closed | Records continuity boundaries without storing socket details |
| User input | finalized transcript, typed text, referenced image/audio | Committed before Engine dispatch when the turn is accepted |
| Assistant output | completed response, interrupted partial response | Coalesced from deltas and committed at a terminal boundary |
| Tool | call requested, result, failure, cancellation | Correlated by `call_id`; intent is committed before execution |
| Delegation | task requested, material progress, result/failure/cancel | Correlated by `worker_id`; high-frequency progress may remain operational only |
| Confirmation | exact action requested, approved/denied/expired | Correlated by `confirmation_id` and action digest |
| Context management | summary/checkpoint, redaction, correction | Derived records; original authority is retained or erased per policy |

Raw PCM chunks, every token delta, transport frames, VAD measurements, heartbeats, and provider debug events do not belong in Conversation Journal. They belong in bounded live buffers, media storage under explicit policy, or Event Ledger.

## Streaming write policy

Conversation Journal must preserve correctness without turning storage into the first-audio critical path.

### Synchronous semantic boundaries

The following records must be durably accepted before the dependent side effect begins when the thread is configured as durable:

- accepted user turn before Conversation Engine dispatch;
- `CallTool` intent before tool execution;
- `DelegateTask` intent before Agent launch;
- confirmation request before it is presented as actionable;
- tool/delegation result before it is reinjected into an Engine or announced as authoritative;
- confirmation decision before the protected action executes.

ASR partials and transcript revisions remain in bounded live events/UI. Only a stable final transcript accepted by Turn Manager as a user turn is appended as `USER_INPUT`, and its durable commit plus Context Visibility Barrier precedes response generation. Input aborted by reconnect, device replacement, overflow, or explicit cancellation does not enter model context; only content-free reason and media-range diagnostics may be recorded.

Later ASR or user correction appends a `CORRECTION` item referencing the original `item_id` rather than mutating history, and invalidates any derived summary covering that source. Empty or policy-low-confidence final text produces an explicit repeat request instead of an empty Journal turn. Raw user audio is not persisted unless a separately authorized recording/replay/training capability is enabled.

### Streamed assistant output

`TextDelta` and `AudioDelta` remain in bounded live response buffers. They are not synchronously appended one by one. On response completion, cancellation, or failure, an assembler writes one canonical assistant item, plus content references when needed.

An interrupted response is recorded as partial/cancelled, not as a normal completed answer. When the client can report playback progress, the item may include a delivery receipt or heard-text/audio boundary. Generated content, transmitted content, and content confirmed as played remain distinct fields or linked records.

This policy prevents database round trips from gating every token or audio chunk while retaining enough state to explain and resume the conversation.

## Conversation Projection

Conversation Engine never reads a provider session as canonical history. A Conversation Projector reads Journal items and builds the context required by a specific target:

```text
Conversation Journal
  ├── Native Realtime Projection (provider items/session updates)
  ├── Pipeline Brain Projection (system + bounded message/tool history)
  ├── Claude Delegation Projection
  ├── Codex Delegation Projection
  └── Hermes Delegation Projection
```

A projector owns:

- mapping canonical item kinds to provider roles/item types;
- context-window selection and token budgeting;
- provider-specific tool-call/result formatting;
- visibility filtering and redaction;
- summary/checkpoint inclusion;
- canonical `item_id` ↔ namespaced provider item ID mapping;
- capability-aware omission or transformation of unsupported content.

Provider acknowledgments never mutate canonical identity. If a provider loses its session, the adapter opens a replacement and replays a bounded projection. Switching Native Realtime Engine to Pipeline Engine—or changing model vendor—uses the same Journal without history migration.

## Summaries and context windows

Summarization is a derived optimization, not destructive truth replacement.

- A summary is a versioned Conversation Item with the exact source sequence range it covers.
- Projectors may use the latest valid summary plus later items to fit a context window.
- Tool results, confirmations, user preferences, and unresolved work cannot be dropped merely because prose was summarized.
- A summary produced by one provider is canonical only as a labeled derived item, not as proof that omitted facts never existed.
- Regeneration or invalidation of a summary does not renumber original items.

Retention policy may erase original content for privacy or legal requirements; that is an explicit redaction/erasure workflow, not ordinary context compaction.

## Concurrency and causal order

Multiple Agents and tools may complete out of order. Journal sequence records acceptance order, while causal IDs preserve semantic relationships.

- optimistic `expected_thread_version` detects conflicting writers when an operation requires a specific predecessor;
- separate Voice Sessions may append to the same explicitly shared Thread; the server assigns one total Journal sequence without merging their Voice Session Phase, Generation, media epochs, or cancellation scope;
- each Response freezes a Context Visibility Barrier at start. Items committed later by another Voice Session become visible to its next projection and are never hot-inserted into an already generating response;
- independent worker completions may append in arrival order and retain their own `worker_id`/parent relation;
- duplicate provider callbacks are deduplicated by stable `item_id` or provider-event idempotency key;
- Conversation Kernel decides whether a late result may affect the current Response Stream; Journal may still retain the result even when its Generation is stale;
- stale output is marked superseded and cannot silently become current dialogue.

Journal sequence is not a global distributed clock. Cross-thread ordering is expressed through explicit correlation and timestamps when needed.

## Restore and reconnect

Restoring a Voice Session uses distinct sources deliberately:

1. load persistent semantic context from Conversation Journal;
2. restore or reconcile active Delegated Tasks from their task backend into Work Registry;
3. create a fresh provider Conversation Projection or reattach a still-valid provider session;
4. bind the new Endpoint Session connection to the existing `voice_session_id`;
5. resume user-visible output only after Generation and pending confirmation state are reconciled.

Replaying Journal items must not re-execute tools, resend confirmations, or relaunch Agents. Execution is driven by explicit Work Registry/task state and idempotency keys, not by treating history records as commands.

## Failure behavior

- If a durable user turn cannot be appended, Engine dispatch does not begin and the client receives an explicit retryable session error.
- If tool/delegation intent cannot be appended, the side effect does not start.
- If a completed tool result cannot be appended, it is retained in the idempotent work backend and retried; it is not announced as durably accepted.
- Assistant-response persistence failure after audio has begun is surfaced as a degraded durability state. It does not claim the user heard nothing, and recovery uses response IDs and delivery receipts.
- Event Ledger or an Observer failure cannot roll back a successful Journal append.
- Projection failure fails the target Engine/Agent request explicitly and leaves canonical history unchanged.

## Privacy and security

- Journal storage is tenant-partitioned and authorization-scoped by `tenant_id`, `user_id`, and `thread_id`.
- Long-lived secrets, provider credentials, and raw authorization headers are forbidden content.
- Raw audio is not stored by default. If enabled, Journal stores an authorized media reference plus retention metadata, not an unbounded inline blob.
- Sensitive tool results may use encrypted content references or visibility-limited items rather than copying secrets into model context.
- Redaction, export, retention expiry, and deletion are explicit store capabilities with auditable outcomes.
- Observability labels use identifiers and outcomes, not raw conversation content.

## Explicit non-goals

- Conversation Journal is not Event Ledger, a tracing backend, or a general event bus.
- It is not the Work Registry and does not supervise active processes.
- It is not a vector database or long-term user-memory system; those may derive data from authorized items behind separate contracts.
- It does not require event-sourcing every internal state transition.
- It does not require raw audio recording.
- It does not make provider session IDs stable domain identities.

## Acceptance checks

1. A thread can move from Pipeline Engine to Native Realtime Engine and back without losing canonical user/tool/assistant history.
2. Destroying a provider session and rebuilding its projection does not change canonical item IDs or re-execute side effects.
3. Replaying Journal reads cannot launch tools or Agents.
4. Duplicate tool/worker callbacks append at most one semantic result.
5. An interrupted assistant answer is distinguishable from a completed one and from what the client reports playing.
6. A slow Event Ledger Observer cannot delay or invalidate a Journal append.
7. Streaming token/audio volume does not create one durable write per delta.
8. Unauthorized tenants/users cannot read or append another thread's items.
9. Summary/checkpoint use is traceable to a precise source range.
10. Durable-mode startup and persistence failures never silently downgrade to volatile history.

## Consequences

- Conversation continuity no longer depends on any model vendor or live provider session.
- Reconnect, Engine replacement, and Claude/Codex/Hermes delegation share one canonical history.
- Tool and confirmation recovery gains explicit idempotency and causal records.
- The first-audio path remains streaming because deltas are coalesced rather than durably written individually.
- A new persistence Seam and projection layer must be implemented and tested; provider adapters become responsible for canonical/provider item mapping.

## References

- OpenAI, [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)
- OpenAI, [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [ADR-0042](0042-thin-conversation-kernel-over-independent-capability-seams.md)
- [ADR-0046](0046-first-class-identity-and-correlation-context.md)
- [ADR-0047](0047-canonical-typed-voice-events-and-conversation-actions.md)
- [ADR-0048](0048-end-to-end-streaming-conversation-engine-and-output-contract.md)
- [ADR-0049](0049-separate-realtime-session-plane-from-application-control-plane.md)
