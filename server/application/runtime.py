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
from server.conversation_journal import (
    ConversationHistoryRetention,
    ConversationJournal,
    JournalScope,
)
from server.observability.telemetry import (
    DiagnosticsQuery,
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryOutcome,
)
from server.persistence.in_memory import InMemoryPersistence
from server.persistence.postgres import (
    PostgresPersistence,
    PostgresSpeechDeliveryStore,
    PostgresTelemetryStore,
)
from server.persistence.postgres.schema import validate_schema_name
from server.persistence.unit_of_work import AgentPersistence
from server.realtime.registry import ActiveRealtimeConversations
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
        speech_deliveries: SpeechDeliveryStore | None = None,
        voice_session_admission: LocalVoiceSessionAdmissionController | None = None,
        pool: Any | None = None,
    ) -> None:
        self.persistence = persistence
        self.telemetry = telemetry
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
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("application runtime is closed")
        if self._agent_result_delivery_task is not None:
            return
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

    @property
    def journal(self) -> ConversationJournal:
        return self.persistence.journal

    @property
    def diagnostics(self) -> DiagnosticsQuery:
        return self.telemetry.diagnostics

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
        selected = tuple(dict.fromkeys(voice_session_ids))
        scopes = tuple(
            JournalScope(tenant_id=tenant_id, user_id=user_id, thread_id=session_id)
            for session_id in selected
        )
        await self.telemetry.flush()
        deleted_threads = await journal.delete_threads(scopes)
        deleted_sessions = await self.telemetry.delete_sessions(selected)
        return {
            "requested": len(selected),
            "deleted_sessions": deleted_sessions,
            "deleted_threads": deleted_threads,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
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
            if self._pool is not None:
                await self._pool.close()


async def build_application_runtime(
    config: ApplicationRuntimeConfig | None = None,
    *,
    postgres_pool_factory: PostgresPoolFactory | None = None,
) -> ApplicationRuntime:
    resolved = config or ApplicationRuntimeConfig.from_env()
    if resolved.state_backend == "memory":
        telemetry = RuntimeTelemetry(InMemoryTelemetryStore())
        await telemetry.start()
        runtime = ApplicationRuntime(
            InMemoryPersistence(),
            telemetry,
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
    pool = await postgres_pool_factory(
        dsn=resolved.postgres_dsn,
        min_size=resolved.postgres_pool_min_size,
        max_size=resolved.postgres_pool_max_size,
    )
    telemetry = RuntimeTelemetry(
        PostgresTelemetryStore(pool, schema=resolved.postgres_schema)
    )
    await telemetry.start()
    runtime = ApplicationRuntime(
        PostgresPersistence(pool, schema=resolved.postgres_schema),
        telemetry,
        speech_deliveries=PostgresSpeechDeliveryStore(
            pool,
            schema=resolved.postgres_schema,
        ),
        voice_session_admission=_voice_session_admission(
            telemetry,
            resolved.voice_capacity_limits(),
        ),
        pool=pool,
    )
    await runtime.start()
    return runtime
