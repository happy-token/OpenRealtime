"""Application composition root for swappable durable state backends."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from server.agent_session.work_registry import AgentWorkRegistry
from server.application.recording import ApplicationRecordingOwner
from server.artifacts import InMemoryArtifactStore
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactStore,
    RecordingPreservation,
    S3ObjectClient,
    validate_recording_preservation,
)
from server.conversation_journal import (
    ConversationHistoryRetention,
    ConversationJournal,
    JournalScope,
    SessionRecordingQuery,
)
from server.conversation_journal.input_evidence import input_evidence_thread_id
from server.conversation_journal.journal import SessionOwnedHistoryRetention
from server.core.interaction_context import InteractionContext
from server.observability.recordings import RecordingUnavailable, SessionRecordingReader
from server.observability.telemetry import (
    DebugLogQuery,
    DiagnosticsQuery,
    InMemoryDebugLogStore,
    InMemoryTelemetryStore,
    RuntimeDebugLog,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryOutcome,
)
from server.persistence.in_memory import InMemoryPersistence
from server.persistence.postgres import (
    PostgresDebugLogStore,
    PostgresPersistence,
    PostgresSpeechDeliveryStore,
    PostgresTelemetryStore,
)
from server.persistence.postgres.conversation_journal import PostgresConversationJournal
from server.persistence.postgres.recording_preservation import (
    PostgresRecordingPreservation,
    lock_session_recordings,
)
from server.persistence.postgres.schema import validate_schema_name
from server.persistence.unit_of_work import AgentPersistence
from server.realtime.recording import SessionAudioRecorder
from server.realtime.registry import ActiveRealtimeConversations, SessionHistoryDeletionConflict
from server.realtime.speech import InMemorySpeechDeliveryStore, SpeechDeliveryStore
from server.voice_session.admission import (
    LocalVoiceSessionAdmissionController,
    VoiceSessionAdmissionObservation,
    VoiceSessionCapacityLimits,
)

PostgresPoolFactory = Callable[..., Awaitable[Any]]
logger = logging.getLogger(__name__)


def _voice_session_admission(
    telemetry: RuntimeTelemetry,
    limits: VoiceSessionCapacityLimits,
) -> LocalVoiceSessionAdmissionController:
    def observe(observation: VoiceSessionAdmissionObservation) -> None:
        identity = observation.identity
        session = telemetry.bind(
            TelemetryIdentity(
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                device_id=identity.device_id,
                voice_session_id=identity.voice_session_id,
                thread_id=identity.thread_id,
            )
        )
        session.record(
            "voice_session.admission",
            generation=0,
            outcome=(
                TelemetryOutcome.DEGRADED
                if observation.decision == "rejected"
                else TelemetryOutcome.OK
            ),
            attributes={
                "decision": observation.decision,
                "reasons": observation.reasons,
                "active_sessions": observation.active_sessions,
                "projected_sessions": observation.projected_sessions,
                "event_loop_lag_ms": observation.event_loop_lag_ms,
                "process_memory_bytes": observation.process_memory_bytes,
                "observed_audio_queue_bytes": observation.observed_audio_queue_bytes,
                "projected_audio_queue_bytes": observation.projected_audio_queue_bytes,
            },
        )

    return LocalVoiceSessionAdmissionController(limits=limits, observer=observe)


@dataclass(frozen=True, slots=True)
class ApplicationRuntimeConfig:
    state_backend: str = "memory"
    postgres_dsn: str | None = None
    postgres_schema: str = "voiceagent"
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 12
    voice_max_active_sessions: int = 8
    voice_max_asr_sessions: int = 8
    voice_max_tts_sessions: int = 8
    voice_max_event_loop_lag_ms: float = 200.0
    voice_max_process_memory_bytes: int = 1_073_741_824
    voice_max_audio_queue_bytes: int = 67_108_864
    voice_audio_queue_reservation_bytes: int = 4_194_304
    voice_capacity_retry_after_ms: int = 1_000

    def __post_init__(self) -> None:
        if self.state_backend not in {"memory", "postgres"}:
            raise ValueError("state_backend must be 'memory' or 'postgres'")
        if self.postgres_pool_min_size < 1:
            raise ValueError("postgres_pool_min_size must be positive")
        if self.postgres_pool_max_size < self.postgres_pool_min_size:
            raise ValueError("postgres_pool_max_size must be >= min_size")
        validate_schema_name(self.postgres_schema)
        self.voice_capacity_limits()

    def voice_capacity_limits(self) -> VoiceSessionCapacityLimits:
        return VoiceSessionCapacityLimits(
            max_active_sessions=self.voice_max_active_sessions,
            max_asr_sessions=self.voice_max_asr_sessions,
            max_tts_sessions=self.voice_max_tts_sessions,
            max_event_loop_lag_ms=self.voice_max_event_loop_lag_ms,
            max_process_memory_bytes=self.voice_max_process_memory_bytes,
            max_audio_queue_bytes=self.voice_max_audio_queue_bytes,
            audio_queue_reservation_bytes=self.voice_audio_queue_reservation_bytes,
            retry_after_ms=self.voice_capacity_retry_after_ms,
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> ApplicationRuntimeConfig:
        values = os.environ if environ is None else environ
        return cls(
            state_backend=values.get("VOICEAGENT_STATE_BACKEND", "memory").strip().lower(),
            postgres_dsn=values.get("VOICEAGENT_POSTGRES_DSN"),
            postgres_schema=values.get("VOICEAGENT_POSTGRES_SCHEMA", "voiceagent"),
            postgres_pool_min_size=int(
                values.get("VOICEAGENT_POSTGRES_POOL_MIN_SIZE", "1")
            ),
            postgres_pool_max_size=int(
                values.get("VOICEAGENT_POSTGRES_POOL_MAX_SIZE", "12")
            ),
            voice_max_active_sessions=int(
                values.get("VOICEAGENT_MAX_ACTIVE_VOICE_SESSIONS", "8")
            ),
            voice_max_asr_sessions=int(
                values.get("VOICEAGENT_MAX_ASR_SESSIONS", "8")
            ),
            voice_max_tts_sessions=int(
                values.get("VOICEAGENT_MAX_TTS_SESSIONS", "8")
            ),
            voice_max_event_loop_lag_ms=float(
                values.get("VOICEAGENT_MAX_EVENT_LOOP_LAG_MS", "200")
            ),
            voice_max_process_memory_bytes=int(
                values.get("VOICEAGENT_MAX_PROCESS_MEMORY_BYTES", "1073741824")
            ),
            voice_max_audio_queue_bytes=int(
                values.get("VOICEAGENT_MAX_AUDIO_QUEUE_BYTES", "67108864")
            ),
            voice_audio_queue_reservation_bytes=int(
                values.get("VOICEAGENT_AUDIO_QUEUE_RESERVATION_BYTES", "4194304")
            ),
            voice_capacity_retry_after_ms=int(
                values.get("VOICEAGENT_CAPACITY_RETRY_AFTER_MS", "1000")
            ),
        )


class ApplicationRuntime:
    """Owns process-wide persistence resources; session logic only sees ports."""

    def __init__(
        self,
        persistence: AgentPersistence,
        telemetry: RuntimeTelemetry,
        *,
        debug_log: RuntimeDebugLog | None = None,
        speech_deliveries: SpeechDeliveryStore | None = None,
        voice_session_admission: LocalVoiceSessionAdmissionController | None = None,
        artifacts: ArtifactStore | None = None,
        recording_storage_durable: bool = False,
        pool: Any | None = None,
        postgres_schema: str = "voiceagent",
    ) -> None:
        self.persistence = persistence
        self.telemetry = telemetry
        self.debug_log = debug_log or RuntimeDebugLog(InMemoryDebugLogStore())
        self.speech_deliveries = speech_deliveries or InMemorySpeechDeliveryStore()
        self.voice_session_admission = (
            voice_session_admission or LocalVoiceSessionAdmissionController()
        )
        self.active_realtime_conversations = ActiveRealtimeConversations()
        self.agent_work_registry = AgentWorkRegistry(persistence.agent_tasks)
        from server.agent_session.result_delivery import AgentResultDeliveryWorker

        self._agent_result_delivery = AgentResultDeliveryWorker(
            persistence=persistence,
            conversations=self.active_realtime_conversations,
        )
        self._agent_result_delivery_owner = f"application-runtime:{uuid.uuid4()}"
        self._agent_result_delivery_stop = asyncio.Event()
        self._agent_result_delivery_task: asyncio.Task[None] | None = None
        self._pool = pool
        self._postgres_schema = validate_schema_name(postgres_schema)
        self._closed = False
        self._closing = False
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self.recordings = ApplicationRecordingOwner(journal=persistence.journal, telemetry=telemetry,
            artifacts=artifacts, storage_durable=recording_storage_durable)

    async def start(self) -> None:
        if self._closed or self._closing:
            raise RuntimeError("application runtime is closed or closing")
        if self._agent_result_delivery_task is not None:
            return
        self.recordings.start()
        self._agent_result_delivery_task = asyncio.create_task(
            self._run_agent_result_delivery(),
            name="agent-result-delivery",
        )

    async def _run_agent_result_delivery(self) -> None:
        while not self._agent_result_delivery_stop.is_set():
            try:
                delivered = await self._agent_result_delivery.deliver_once(
                    owner=self._agent_result_delivery_owner,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("agent result delivery poll failed")
                delivered = ()
            if delivered:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(
                    self._agent_result_delivery_stop.wait(),
                    timeout=0.05,
                )
            except TimeoutError:
                pass

    def open_recording(self, context: InteractionContext) -> SessionAudioRecorder | None:
        return self.recordings.open(context)

    @property
    def journal(self) -> ConversationJournal:
        return self.persistence.journal

    @property
    def diagnostics(self) -> DiagnosticsQuery:
        return self.telemetry.diagnostics

    @property
    def debug_log_query(self) -> DebugLogQuery:
        return self.debug_log.query

    def diagnostics_health(self) -> dict[str, Any]:
        telemetry = self.telemetry.collection_health()
        debug_log = self.debug_log.collection_health()
        return {"status": "degraded" if telemetry["status"] != "ok" or debug_log["status"] != "ok" else "ok", "telemetry": telemetry, "debug_log": debug_log}

    async def session_history_scope(self, voice_session_id: str, *, tenant_id: str, user_id: str,
                                    require_complete: bool = False) -> JournalScope:
        """Resolve server-recorded identity, never reconstruct it from the admin account."""
        detail = await self.diagnostics.session_detail(voice_session_id)
        if require_complete and detail is not None and detail.next_cursor is not None:
            raise ValueError("session history identity is incomplete")
        if detail is not None and detail.events:
            scopes = {JournalScope(event.tenant_id, event.user_id, event.thread_id) for event in detail.events}
            if len(scopes) != 1:
                raise ValueError("session history identity is ambiguous")
            return next(iter(scopes))
        return JournalScope(tenant_id, user_id, voice_session_id)

    async def preserve_session_recordings(self, session_id: str, *, actor_id: str) -> dict[str, Any]:
        """Internal admin operation; source proof and real mutation remain owned after timeout."""
        validate_recording_preservation(session_id, actor_id)
        return await self.recordings.run_owned_operation(
            session_id, lambda: self._preserve_session_recordings(session_id, actor_id=actor_id)
        )

    async def _preserve_session_recordings(self, session_id: str, *, actor_id: str) -> dict[str, Any]:
        store = self.recordings.artifacts
        if not isinstance(store, RecordingPreservation):
            raise RecordingUnavailable(503, "recording_preservation_not_configured")
        source = await SessionRecordingReader(self.journal, store).source_scope(session_id)
        if source is None:
            raise RecordingUnavailable(404, "recording_source_not_found")
        scope = ArtifactAccessScope(source.tenant_id, source.user_id)
        if self._pool is not None:
            async with self._pool.acquire() as connection, connection.transaction():
                await lock_session_recordings(connection, self._postgres_schema, scope, session_id)
                fresh = await SessionRecordingReader(
                    PostgresConversationJournal(connection, schema=self._postgres_schema), store
                ).source_scope(session_id)
                if fresh != source:
                    raise RecordingUnavailable(409, "recording_source_changed")
                state = await PostgresRecordingPreservation(
                    connection, schema=self._postgres_schema
                ).preserve_session_for(scope, session_id, actor_id=actor_id)
        else:
            async with self.recordings.volatile_history_guard():
                fresh = await SessionRecordingReader(self.journal, store).source_scope(session_id)
                if fresh != source:
                    raise RecordingUnavailable(409, "recording_source_changed")
                state = await store.preserve_session_for(scope, session_id, actor_id=actor_id)
        return {
            "voice_session_id": state.voice_session_id,
            "preserved": True,
            "marked_at": state.marked_at.isoformat(),
            "preserved_segments": state.preserved_segments,
            "pending_segments": state.pending_segments,
            "unavailable_segments": state.unavailable_segments,
            "storage_durable": self.recordings.storage_status == "durable",
        }

    async def delete_session_history(
        self,
        voice_session_ids: Sequence[str],
        *,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, int]:
        journal = self.journal
        if not isinstance(journal, ConversationHistoryRetention):
            raise TypeError("configured conversation journal does not support deletion")
        if not self.telemetry.supports_session_deletion:
            raise TypeError("configured telemetry store does not support deletion")
        if not self.debug_log.supports_session_deletion:
            raise TypeError("configured debug log store does not support deletion")
        selected = tuple(dict.fromkeys(voice_session_ids))
        await self.telemetry.flush()
        resolved = [await self.session_history_scope(session_id, tenant_id=tenant_id, user_id=user_id)
                    for session_id in selected]
        if isinstance(journal, SessionRecordingQuery):
            reader = SessionRecordingReader(journal, self.recordings.artifacts)
            resolved = [await reader.source_scope(session_id) or scope
                        for session_id, scope in zip(selected, resolved)]
        # A conversation thread may be shared by several resumed sessions; never delete it wholesale.
        evidence_scopes = tuple(
            JournalScope(tenant_id=scope.tenant_id, user_id=scope.user_id,
                         thread_id=input_evidence_thread_id(scope.thread_id, session_id))
            for scope, session_id in zip(resolved, selected)
        )
        recording_scopes = tuple(
            JournalScope(scope.tenant_id, scope.user_id, f"{scope.thread_id}::recording:{session_id}")
            for scope, session_id in zip(resolved, selected))
        candidates = tuple((scope.tenant_id, scope.user_id, scope.thread_id)
                           for scope, session_id in zip(resolved, selected) if scope.thread_id == session_id)
        sessions = tuple((scope.tenant_id, scope.user_id, session_id)
                         for scope, session_id in zip(resolved, selected))
        with (
            self.recordings.deletion_guard(sessions),
            self.active_realtime_conversations.session_deletion_guard(sessions),
            self.active_realtime_conversations.thread_deletion_guard(candidates) as reserved,
        ):
            scopes = tuple(scope for scope in resolved if (scope.tenant_id, scope.user_id, scope.thread_id) in reserved)
            if self._pool is not None:
                await self.debug_log.flush()
                async with (
                    self._pool.acquire() as connection,
                    connection.transaction(),
                ):
                    for source_tenant, source_user, session_id in sorted(sessions):
                        await lock_session_recordings(
                            connection, self._postgres_schema,
                            ArtifactAccessScope(source_tenant, source_user), session_id,
                        )
                    if await connection.fetchval(
                        f'SELECT EXISTS(SELECT 1 FROM "{self._postgres_schema}".session_recording_preservation WHERE voice_session_id=ANY($1::text[]))',
                        list(selected),
                    ):
                        raise SessionHistoryDeletionConflict("Session recording history is preserved")
                    fresh_reader = SessionRecordingReader(
                        PostgresConversationJournal(connection, schema=self._postgres_schema),
                        self.recordings.artifacts,
                    )
                    for session_id, source in zip(selected, resolved):
                        fresh = await fresh_reader.source_scope(session_id)
                        if fresh is not None and fresh != source:
                            raise SessionHistoryDeletionConflict("Session history source changed")
                    await PostgresDebugLogStore(connection, schema=self._postgres_schema).delete_sessions(selected)
                    deleted_threads = await PostgresConversationJournal(connection, schema=self._postgres_schema).delete_session_owned_threads(scopes, selected)
                    deleted_evidence_threads = await PostgresConversationJournal(connection, schema=self._postgres_schema).delete_threads(evidence_scopes)
                    deleted_recording_threads = await PostgresConversationJournal(connection, schema=self._postgres_schema).delete_threads(recording_scopes)
                    stop_store = PostgresSpeechDeliveryStore(connection, schema=self._postgres_schema)
                    deleted_output_stop_facts = sum([
                        await stop_store.delete_output_stop_facts(
                            tenant_id=scope.tenant_id, user_id=scope.user_id,
                            thread_id=scope.thread_id, voice_session_id=session_id)
                        for scope, session_id in zip(resolved, selected)
                    ])
                    deleted_sessions = await PostgresTelemetryStore(connection, schema=self._postgres_schema).delete_sessions(selected)
                return {"requested": len(selected), "deleted_sessions": deleted_sessions, "deleted_threads": deleted_threads, "deleted_evidence_threads": deleted_evidence_threads, "deleted_recording_threads": deleted_recording_threads, "deleted_output_stop_facts": deleted_output_stop_facts}
            async with self.recordings.volatile_history_guard(deleting=selected):
                await self.debug_log.delete_sessions(selected)
                deleted_threads = await journal.delete_session_owned_threads(scopes, selected) if isinstance(journal, SessionOwnedHistoryRetention) else 0
                deleted_evidence_threads = await journal.delete_threads(evidence_scopes)
                deleted_recording_threads = await journal.delete_threads(recording_scopes)
                deleted_output_stop_facts = sum([
                    await self.speech_deliveries.delete_output_stop_facts(
                        tenant_id=scope.tenant_id, user_id=scope.user_id,
                        thread_id=scope.thread_id, voice_session_id=session_id)
                    for scope, session_id in zip(resolved, selected)
                ])
                deleted_sessions = await self.telemetry.delete_sessions(selected)
                return {
                    "requested": len(selected),
                    "deleted_sessions": deleted_sessions,
                    "deleted_threads": deleted_threads,
                    "deleted_evidence_threads": deleted_evidence_threads,
                    "deleted_recording_threads": deleted_recording_threads,
                    "deleted_output_stop_facts": deleted_output_stop_facts,
                }

    async def close(self) -> None:
        if self._close_task is None or (self._close_task.done() and not self._closed):
            self._close_task = asyncio.create_task(self._close_resources(), name="application-resource-close")
            self._close_task.add_done_callback(self._close_completed)
        await asyncio.shield(self._close_task)

    @staticmethod
    def _close_completed(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieve a late failure even after a caller leaves.

    async def _close_resources(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            # A timed-out write may still need metadata/Journal after object put.
            # Keep resources open and allow a later close retry after actual exit.
            await self.recordings.close()
            self._agent_result_delivery_stop.set()
            if self._agent_result_delivery_task is not None:
                self._agent_result_delivery_task.cancel()
                await asyncio.gather(
                    self._agent_result_delivery_task,
                    return_exceptions=True,
                )
                self._agent_result_delivery_task = None
            try:
                await self.telemetry.close()
            finally:
                try:
                    await self.debug_log.close()
                finally:
                    if self._pool is not None:
                        await self._pool.close()
            self._closed = True


async def build_application_runtime(
    config: ApplicationRuntimeConfig | None = None,
    *,
    postgres_pool_factory: PostgresPoolFactory | None = None,
    object_client_factory: Callable[[], S3ObjectClient] | None = None,
) -> ApplicationRuntime:
    resolved = config or ApplicationRuntimeConfig.from_env()
    if resolved.state_backend == "memory":
        telemetry = RuntimeTelemetry(InMemoryTelemetryStore())
        await telemetry.start()
        debug_log = RuntimeDebugLog(InMemoryDebugLogStore())
        await debug_log.start()
        runtime = ApplicationRuntime(
            InMemoryPersistence(),
            telemetry,
            debug_log=debug_log,
            artifacts=InMemoryArtifactStore(),
            voice_session_admission=_voice_session_admission(
                telemetry,
                resolved.voice_capacity_limits(),
            ),
        )
        await runtime.start()
        return runtime
    if not resolved.postgres_dsn:
        raise ValueError(
            "VOICEAGENT_POSTGRES_DSN is required when "
            "VOICEAGENT_STATE_BACKEND=postgres"
        )
    if postgres_pool_factory is None:
        try:
            import asyncpg
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "PostgreSQL state requires the 'postgres' optional dependency"
            ) from error
        postgres_pool_factory = asyncpg.create_pool
    # Configure storage before opening process resources. Partial explicit S3
    # configuration is an error; no secrets configured is observable unavailability.
    objects = None
    if object_client_factory is not None:
        objects = object_client_factory()
    elif any(os.environ.get(name, "").strip() for name in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_AK", "S3_SK")):
        from server.artifacts.boto3_factory import build_s3_object_client_from_env
        objects = build_s3_object_client_from_env()
    pool = await postgres_pool_factory(
        dsn=resolved.postgres_dsn,
        min_size=resolved.postgres_pool_min_size,
        max_size=resolved.postgres_pool_max_size,
    )
    telemetry = RuntimeTelemetry(
        PostgresTelemetryStore(pool, schema=resolved.postgres_schema)
    )
    await telemetry.start()
    debug_log = RuntimeDebugLog(
        PostgresDebugLogStore(pool, schema=resolved.postgres_schema)
    )
    await debug_log.start()
    from server.persistence.postgres.artifact_store import PostgresArtifactStore

    runtime = ApplicationRuntime(
        PostgresPersistence(pool, schema=resolved.postgres_schema),
        telemetry,
        debug_log=debug_log,
        speech_deliveries=PostgresSpeechDeliveryStore(
            pool,
            schema=resolved.postgres_schema,
        ),
        voice_session_admission=_voice_session_admission(
            telemetry,
            resolved.voice_capacity_limits(),
        ),
        artifacts=PostgresArtifactStore(pool, objects=objects, schema=resolved.postgres_schema) if objects is not None else None,
        recording_storage_durable=objects is not None,
        pool=pool,
        postgres_schema=resolved.postgres_schema,
    )
    await runtime.start()
    return runtime
