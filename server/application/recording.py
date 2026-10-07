"""Process resource ownership for recording writes and Artifact expiry cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from server.artifacts.protocol import ArtifactCleanup, ArtifactStore
from server.conversation_journal import ConversationJournal
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import RuntimeTelemetry, TelemetryIdentity, TelemetryOutcome
from server.realtime.recording import SessionAudioRecorder
from server.realtime.registry import SessionHistoryDeletionConflict

logger = logging.getLogger(__name__)
SessionKey = tuple[str, str, str]


class RecordingWritesPending(RuntimeError):
    """Resources remain owned until real writes finish; retry shutdown afterwards."""


class ApplicationRecordingOwner:
    """Storage ownership only. Never decides a turn, interruption, or playback fact."""

    def __init__(
        self,
        *,
        journal: ConversationJournal,
        telemetry: RuntimeTelemetry,
        artifacts: ArtifactStore | None,
        storage_durable: bool,
    ) -> None:
        self.artifacts = artifacts
        self._journal = journal
        self._telemetry = telemetry
        self._durable = storage_durable
        self._recorders: dict[SessionKey, tuple[InteractionContext, SessionAudioRecorder]] = {}
        self._deleting: set[SessionKey] = set()
        self._closing = False
        self._stop = asyncio.Event()
        self._maintenance: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[object] | None = None
        self._cleanup_interval_s = 60.0

    @property
    def storage_status(self) -> str:
        if self.artifacts is None:
            return "not-configured"
        return "durable" if self._durable else "volatile"

    def _observe(
        self,
        context: InteractionContext,
        status: str,
        *,
        recorder: SessionAudioRecorder | None = None,
        reason: str | None = None,
    ) -> None:
        try:
            session = self._telemetry.bind(
                TelemetryIdentity(
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    device_id=context.device_id,
                    voice_session_id=context.voice_session_id,
                    thread_id=context.thread_id,
                )
            )
            session.record(
                "recording.status",
                generation=context.generation,
                outcome=TelemetryOutcome.DEGRADED
                if status in {"failed", "not-configured"}
                else TelemetryOutcome.OK,
                attributes={
                    "status": status,
                    "storage_durable": self._durable,
                    "completed_segments": recorder.completed_segments if recorder else 0,
                    "reason": reason,
                },
            )
        except (Exception, asyncio.CancelledError):  # noqa: BLE001 - isolate optional observers
            logger.warning("Recording telemetry observer failed")

    def open(self, context: InteractionContext) -> SessionAudioRecorder | None:
        if self._closing:
            raise RuntimeError("recording owner is closing")
        key = (context.tenant_id, context.user_id, context.voice_session_id)
        if key in self._deleting:
            raise SessionHistoryDeletionConflict("recording history is being deleted")
        existing = self._recorders.get(key)
        if existing is not None:
            if existing[0] != context:
                raise ValueError("recording Session identity was reused")
            return existing[1]
        if self.artifacts is None:
            self._observe(context, "not-configured")
            return None
        if len(self._recorders) >= 64:
            self._observe(context, "failed", reason="recording_global_budget")
            return None

        # The closure is invoked only asynchronously after this registration.
        def settled() -> None:
            self._recorders.pop(key, None)
            self._observe(
                context,
                "failed" if recorder.failure else "settled",
                recorder=recorder,
                reason=recorder.failure,
            )

        recorder = SessionAudioRecorder(
            context=context,
            artifacts=self.artifacts,
            journal=self._journal,
            storage_durable=self._durable,
            on_failure=lambda reason: self._observe(context, "failed", reason=reason),
            on_settled=settled,
        )
        self._recorders[key] = (context, recorder)
        self._observe(context, "active", recorder=recorder)
        return recorder

    @contextmanager
    def deletion_guard(self, keys: Sequence[SessionKey]) -> Iterator[None]:
        selected = set(keys)
        if selected & (self._deleting | self._recorders.keys()):
            raise SessionHistoryDeletionConflict(
                "recording writes still own this Session; close and wait for settlement"
            )
        self._deleting.update(selected)
        try:
            yield
        finally:
            self._deleting.difference_update(selected)

    def start(self) -> None:
        if self._maintenance is None and isinstance(self.artifacts, ArtifactCleanup):
            self._maintenance = asyncio.create_task(
                self._run_cleanup(), name="recording-artifact-cleanup"
            )

    async def _run_cleanup(self) -> None:
        # Wait before the first scan: no migration or external request on startup.
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._cleanup_interval_s)
                return
            except TimeoutError:
                pass
            artifacts = self.artifacts
            if not isinstance(artifacts, ArtifactCleanup):
                return
            task = asyncio.create_task(artifacts.reconcile_cleanup_ledger(limit=100))
            self._cleanup = task
            task.add_done_callback(self._cleanup_done)
            stop_wait = asyncio.create_task(self._stop.wait())
            try:
                await asyncio.wait((task, stop_wait), return_when=asyncio.FIRST_COMPLETED)
                if not task.done():
                    return  # Keep the actual operation owned after shutdown starts.
            finally:
                stop_wait.cancel()
                await asyncio.gather(stop_wait, return_exceptions=True)

    def _cleanup_done(self, task: asyncio.Task[object]) -> None:
        if task.cancelled() or task.exception() is not None:
            logger.warning("Recording Artifact cleanup failed; retained ledger allows retry")
        if self._cleanup is task:
            self._cleanup = None

    async def close(self, *, timeout_s: float = 1) -> None:
        self._closing = True
        self._stop.set()
        if self._maintenance is not None:
            await asyncio.shield(self._maintenance)
            self._maintenance = None
        await asyncio.gather(
            *(
                recorder.close(timeout_s=timeout_s)
                for _, recorder in tuple(self._recorders.values())
            )
        )
        if self._recorders or self._cleanup is not None:
            raise RecordingWritesPending(
                "recording IO remains owned; persistence resources must stay open"
            )
