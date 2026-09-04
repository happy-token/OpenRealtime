---
status: accepted
---

# Use PostgreSQL for authoritative state and S3-compatible storage for large artifacts

OpenRealtime will use PostgreSQL directly as the only production authoritative metadata store. Conversation Journal, Agent Task Store, tool/confirmation state, Workspace Leases, result-delivery state, idempotency records, and Transactional Outbox share PostgreSQL transaction boundaries behind modular repository Protocols. Raw audio when explicitly retained, generated media, large Agent results, archives, patches, and other blobs live in an S3-compatible Artifact Store; PostgreSQL stores their metadata and opaque Artifact References.

In-memory conformers remain for deterministic unit tests. SQLite is not a production or intermediate implementation target. The earlier SQLite suggestion optimized local bootstrap, but it would introduce an avoidable migration and weak operational fit for the accepted multi-Agent design: multiple Supervisor replicas, concurrent task claiming, durable leases/fencing, transactional outbox, tenant isolation, online migrations, and high-contention idempotent create-or-get.

This is OpenRealtime infrastructure, not a claim about GPT Voice/OpenAI private storage.

## Implementation status

The persistence foundation is implemented:

- `PostgresAgentTaskStore` persists versioned requests, explicit selection state,
  run handles, semantic deduplication guards, and revision/CAS transitions;
- `PostgresOutboxStore` uses bounded `FOR UPDATE SKIP LOCKED` claims, expiring
  leases, and monotonic fencing tokens;
- `PostgresPersistence` exposes both repositories on one transaction through a
  modular Unit of Work;
- PostgreSQL conformers now also cover Conversation Journal, canonical Agent
  events, tool decisions/confirmations/grants, and Artifact metadata;
- `AgentTaskSupervisor` commits task selection, Backend Commit Point, and dispatch
  Outbox atomically; its message-type-scoped dispatcher uses task attempt fencing
  and Driver capability negotiation to prevent blind duplicate Agent spawn;
- the versioned migration is applied explicitly rather than at application startup;
- the application composition root selects `memory` for an explicit local/demo
  process or `postgres` through `VOICEAGENT_STATE_BACKEND`, owns the asyncpg pool,
  and gives every live Voice Session the same repository contracts; choosing
  PostgreSQL requires `VOICEAGENT_POSTGRES_DSN` and never silently falls back;
- `ArtifactStore` and `S3ObjectClient` contracts define the staged upload,
  verification, availability, integrity, retention, and deletion boundaries, with
  deterministic in-memory conformers and an injected boto3-compatible client
  adapter; PostgreSQL is authoritative for metadata while object bytes remain in
  the S3-compatible store.

The PostgreSQL adapters are exercised against real PostgreSQL for concurrent
idempotency, semantic deduplication, CAS, rollback, claim, fencing, Journal
ordering, Agent event ingestion, single-use tool grants, and Artifact lifecycle.
A deployment-level MinIO/S3 integration environment, scheduled Artifact garbage
collector, and operator-driven reconciliation queue remain subsequent slices.
No SQLite adapter or temporary production path will be introduced.

## Why PostgreSQL directly

The accepted architecture now needs database behavior rather than merely persistence:

- atomic unique constraints for `delegation_request_id`, `item_id`, callback IDs, confirmation IDs, and delivery keys;
- concurrent worker claiming with row locks and `FOR UPDATE SKIP LOCKED`;
- durable leases and monotonic fencing tokens across multiple processes/hosts;
- transactional creation of Journal item + Agent task + dispatch outbox;
- optimistic revisions/CAS for task, confirmation, and delivery state machines;
- per-thread sequence allocation and deterministic ordering;
- JSONB for versioned typed payload portions alongside indexed relational columns;
- tenant-aware authorization, audit, retention, and optional/production RLS defense in depth;
- online schema migration, backup, point-in-time recovery, monitoring, and replication;
- eventual PostgreSQL notifications or a queue bridge without making the database an ad hoc event bus.

SQLite can implement some uniqueness and local transactions but not this multi-replica operating model without special single-writer constraints and a later data/lease migration. Starting with PostgreSQL removes a temporary architecture layer. Local development cost is handled by containers, not by changing production semantics.

## Storage ownership

| Data | PostgreSQL | S3-compatible Artifact Store |
|---|---:|---:|
| Thread/Voice Session identities | Authoritative | No |
| Conversation Items and semantic text | Authoritative | Only exceptionally large content via reference |
| Agent Task lifecycle/progress/result metadata | Authoritative | Large result bodies/artifacts only |
| Tool call, policy grant, confirmation, idempotency | Authoritative | No secrets; optional large sanitized output via reference |
| Outbox, delivery state, leases/fencing | Authoritative | No |
| Raw input/output audio | Metadata/reference only; disabled by default | Object when retention policy explicitly enables it |
| Generated speech/media | Metadata/reference | Object when replay/download is required |
| Code archives, patches, reports, logs too large for records | Metadata/reference | Object |
| Small structured JSON/text results | Inline, size-limited | No |
| Credentials/API keys | Credential system reference only | Never |

Neither storage system becomes Event Ledger. Operational metrics/traces use observability sinks; selected durable audit facts may be represented as explicit database records.

## Modular persistence contracts

Core modules depend on Protocols, not SQLAlchemy/asyncpg/S3 SDK types:

- `ConversationJournal`;
- `AgentTaskStore`;
- `ToolExecutionStore`;
- `ConfirmationStore`;
- `WorkspaceLeaseStore`;
- `ResultDeliveryStore`;
- `OutboxStore`;
- `ArtifactStore`.

PostgreSQL adapters may share one pool and schema package. Artifact Store has an S3-compatible conformer and an in-memory/fake conformer for tests. Replacing S3 with another object store does not change canonical Artifact Reference or database records.

Repositories that participate in one state transition execute through a common Persistence Unit of Work:

```python
async with persistence.unit_of_work() as uow:
    item = await uow.journal.append(...)
    task = await uow.agent_tasks.create_or_get(...)
    await uow.outbox.enqueue(...)
```

This does not create one god repository. Each contract remains independently testable, while the PostgreSQL implementation exposes a shared transaction where correctness requires it.

## Required atomic transactions

At minimum, these operations are one PostgreSQL transaction:

1. accepted user turn + thread sequence update;
2. Delegation Request Conversation Item + idempotent Agent Task Record + dispatch outbox;
3. tool intent + policy decision/grant + execution outbox;
4. Bound Confirmation request/decision + protected-action outbox;
5. terminal Agent/tool result metadata + Conversation Item + result-delivery outbox;
6. Workspace Lease acquisition/renewal/release + fencing-token update;
7. result notification claimed/delivered state transition;
8. Artifact Reference finalization + Journal/task association after object verification.

No network publish, Agent spawn, tool side effect, S3 URL exposure, or user-visible authoritative result occurs before its database transaction commits.

## Transactional Outbox

PostgreSQL cannot atomically commit a database transaction with a queue, Agent process, provider API, or S3 operation. Every asynchronous side effect starts from Transactional Outbox rows committed with the source state.

Outbox records contain:

- stable `outbox_id` and idempotency/deduplication key;
- tenant, aggregate type/ID, event/action type, schema version;
- small versioned payload or Artifact Reference;
- creation/availability time, attempt count, lease owner/expiry, fencing token;
- delivery status and terminal error metadata.

Dispatchers claim bounded batches using `FOR UPDATE SKIP LOCKED`, commit the lease, execute outside the transaction, then mark outcome idempotently. Consumers are at-least-once and must deduplicate using the stable key. An outbox row is not deleted immediately on success; retention supports audit/reconciliation.

Event Ledger may observe outbox lifecycle but cannot replace it.

## PostgreSQL task leases and fencing

Agent/task dispatch uses database time and revisioned rows:

```text
SELECT ...
FROM agent_tasks
WHERE phase = 'QUEUED' AND available_at <= clock_timestamp()
ORDER BY priority, created_at
FOR UPDATE SKIP LOCKED
LIMIT ...
```

Lease acquisition atomically sets `lease_owner`, `lease_expires_at`, increments a `BIGINT fencing_token`, and advances record revision. Subsequent mutations include the expected revision/fencing token. An expired worker cannot write progress/result after another owner takes over.

Lease expiry means ownership may be recovered; it does not mean the external Agent never started. ADR-0052/0054 reconciliation and Backend Commit Point rules still apply before dispatching anything new.

PostgreSQL advisory locks may be used sparingly for singleton maintenance or migrations, not as the durable task state. Row state and fencing remain inspectable authority.

## Schema shape

Canonical identity/order/filter fields are relational columns, including:

- `tenant_id`, `user_id`, `thread_id`, `voice_session_id`, `turn_id`;
- `item_id`, thread `sequence`, `worker_id`, `call_id`, `confirmation_id`;
- task phase/revision/lease/fencing/selected Agent;
- artifact lifecycle/digest/size/classification;
- timestamps, schema version, status, and idempotency keys.

Versioned, bounded content that varies by item/event kind may use JSONB. The schema will not store each aggregate as one opaque JSON document: unique constraints, authorization predicates, retention, and queue/lease scans require first-class columns.

Large text/JSON has explicit inline size ceilings. Above the ceiling it is serialized to Artifact Store and the row contains an Artifact Reference. Secrets are not moved to S3 merely because they are large.

## S3-compatible Artifact Store

The core contract is S3-compatible rather than AWS-account-specific. Production may use AWS S3 or another approved compatible service; local integration uses MinIO or an equivalent disposable emulator.

Artifact metadata includes:

- opaque `artifact_id` and tenant/owner/source IDs;
- logical kind, media type, byte size, cryptographic digest, and optional encoding;
- storage provider/bucket/key/version/ETag in private adapter metadata;
- classification, visibility, encryption profile, retention/expiry/legal-hold policy;
- lifecycle: `STAGING`, `AVAILABLE`, `QUARANTINED`, `DELETING`, `DELETED`, or `FAILED`;
- source `worker_id`/tool call/Conversation Item and creation/finalization timestamps;
- scanning/validation outcome when applicable.

Canonical records expose only `artifact_id` plus safe metadata. Bucket names, object keys, permanent URLs, credentials, and server-side encryption keys never enter model context.

Objects are private, encrypted in transit and at rest, tenant-scoped, and accessed through short-lived authorized URLs or server streaming. Object keys use opaque IDs; digest is metadata for integrity/content addressing without leaking predictable cross-tenant names.

## PostgreSQL–S3 consistency workflow

There is no distributed transaction between PostgreSQL and S3. Artifact lifecycle is a small saga.

### Upload/finalize

1. In PostgreSQL create `artifact_id` with `STAGING`, expected tenant/kind/limits, and idempotency key.
2. Upload to a staging object key using server credentials or a narrowly scoped short-lived upload URL.
3. Verify object existence, size, digest, media policy, encryption, and optional malware/content scan.
4. In one PostgreSQL transaction mark `AVAILABLE`, store verified private locator metadata, link it to Journal/task/tool result, and enqueue any downstream outbox event.
5. Only AVAILABLE artifacts may be projected to models or downloaded by users.

Retries reuse the same `artifact_id`/upload idempotency key. Concurrent finalize uses record revision/CAS.

### Failure and garbage collection

- upload failure leaves STAGING with retry/expiry;
- object exists but database finalize fails: retry finalization using deterministic `artifact_id`, do not upload another object blindly;
- database row exists but object is missing/corrupt: mark FAILED/QUARANTINED and prevent projection;
- unreferenced staging objects older than policy are garbage-collected after cross-check;
- database deletion/retention expiry first marks DELETING and enqueues object deletion; successful deletion then marks DELETED;
- object-delete failure is retried and remains visible to operations;
- legal hold overrides garbage collection/deletion.

Object-store events are hints for reconciliation, not authority over tenant/task identity.

## Audio policy

Live audio remains on the latency-critical Session Plane and is not routed through PostgreSQL/S3 during playback.

- raw user audio retention is off by default;
- when enabled by explicit tenant/user policy, audio chunks are assembled/segmented outside the realtime loop and uploaded asynchronously;
- Conversation Journal stores transcript/semantic items and optional Artifact Reference after finalization;
- generated output audio is retained only when replay/audit/product requirements justify it;
- Barge-in and playback completion are runtime events; persistence cannot delay cancellation or first audio;
- retention, consent, residency, encryption, and deletion apply independently from text history.

This keeps S3 off the first-audio path.

## Large Agent artifacts

Agent output uses an artifact manifest with `artifact_id`, logical path/name, media type, digest, size, source worker, and disposition. Supervisor uploads from the Workspace Lease boundary, verifies it, then makes the Artifact Reference AVAILABLE.

Another Agent receives authorized references through Handoff Package. It does not receive a permanent S3 URL or implicit access to the source workspace. Large stdout/debug logs are size-limited and classified; secrets and unrestricted workspace archives are rejected/redacted before upload.

## Tenant isolation and security

- every authoritative table and artifact row carries `tenant_id`;
- repository methods require Interaction Context and include tenant predicates;
- production PostgreSQL roles use least privilege; tenant-scoped Row-Level Security is required where the deployment shares tables across tenants, as defense in depth rather than sole authorization;
- connection pool resets transaction/session tenant state before reuse;
- S3 access is private and tenant-scoped through service roles/policies and opaque prefixes;
- presigned URLs are short-lived, minimally scoped, never journaled, and cannot list buckets;
- encryption key policy and data residency are selected from tenant policy;
- database backups and object versions obey the same retention/deletion commitments;
- audit records identify access/decision without placing raw content in metric labels.

## Migrations and compatibility

Schema migrations are versioned, reviewed, and run separately from request startup in production. They support expand/migrate/contract deployment across rolling application versions. Destructive drops require retention/export review and are not bundled with ordinary startup.

PostgreSQL adapter and canonical payload schemas version independently. Unknown payload versions remain explicit. Backfills are idempotent and resumable. Index creation for large tables uses online/concurrent techniques where supported.

The implementation library (`asyncpg`, psycopg, or SQLAlchemy async) is not part of the domain contract. Selection should favor explicit PostgreSQL transaction/control support, pool health, typed mappings, migration tooling, and testability; core modules must never import it directly.

## Local development and tests

- pure domain/repository unit tests use InMemory conformers;
- persistence contract/integration tests use real PostgreSQL, not SQLite pretending to be PostgreSQL;
- Artifact Store integration tests use MinIO or an approved S3-compatible emulator plus a small number of gated real-S3 smoke tests;
- local development uses containerized PostgreSQL + MinIO with nonproduction credentials/buckets;
- tests cover database restart, concurrent claims, transaction rollback, lease expiry/fencing, duplicate callbacks/outbox delivery, S3 upload/finalize failure, garbage collection, and tenant isolation;
- CI may split fast unit and slower integration suites but cannot declare the persistence adapter production-ready without the real PostgreSQL suite.

Install the PostgreSQL adapter explicitly and point the gated suite at an isolated
test database. The suite creates and drops only a unique schema per test:

```bash
uv sync --extra postgres
VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 \
VOICEAGENT_POSTGRES_TEST_DSN='postgresql:///voiceagent_test' \
uv run pytest -q tests/persistence/test_postgres_persistence.py
```

Application startup must not call `apply_migrations`; deployment automation invokes
the versioned migration runner before rolling out code that depends on the new schema.

## Acceptance checks

1. Delegation request, task record, and dispatch outbox commit atomically or not at all.
2. Concurrent create-or-get and task claims across multiple processes produce one task/start owner.
3. Stale fencing token cannot update task/result after lease takeover.
4. Outbox redelivery cannot duplicate Agent spawn, tool side effect, or user notification.
5. Journal per-thread sequence remains unique and ordered under concurrency.
6. S3 upload cannot become visible before verified AVAILABLE metadata commits.
7. PostgreSQL/S3 partial failure is reconciled without lost references or uncontrolled duplicate objects.
8. Raw audio retention off means no audio object/metadata is created.
9. Large artifact download requires matching tenant/user policy and returns only a short-lived access path.
10. One tenant cannot query another tenant's rows or objects through repository, direct application role, or presigned access.
11. Realtime first-audio/Barge-in path operates when object storage is slow or unavailable.
12. Database migrations and rollback/forward compatibility are tested against at least adjacent application schema versions.

## Consequences

- OpenRealtime starts with production multi-replica persistence semantics rather than planning a SQLite migration.
- Journal, Agent Supervisor, tools, confirmation, leases, outbox, and delivery can share atomic transactions while remaining modular contracts.
- S3 handles large media/artifacts efficiently without bloating relational rows or the realtime path.
- Local setup gains PostgreSQL/MinIO containers and persistence dependencies.
- PostgreSQL/S3 consistency requires explicit artifact and outbox state machines, reconciliation workers, and operational monitoring.
- Multi-node scale still requires careful pool sizing, indexing, vacuum/retention, queue/backpressure, and object lifecycle policy; choosing PostgreSQL/S3 does not remove those responsibilities.

## References

- [ADR-0046](0046-first-class-identity-and-correlation-context.md)
- [ADR-0049](0049-separate-realtime-session-plane-from-application-control-plane.md)
- [ADR-0050](0050-server-owned-conversation-journal-as-authoritative-history.md)
- [ADR-0052](0052-durable-agent-task-supervisor-deduplication-and-result-delivery.md)
- [ADR-0053](0053-isolated-agent-execution-sessions-and-codex-first-driver.md)
- [ADR-0054](0054-explicit-agent-selection-plans-and-no-silent-fallback.md)
