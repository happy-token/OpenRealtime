"""Server-authoritative lifecycle for one live Voice Session."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, cast

from server.voice_session.models import (
    VoiceSessionClosed,
    VoiceSessionDisposition,
    VoiceSessionEvent,
    VoiceSessionFailed,
    VoiceSessionFailureCode,
    VoiceSessionIdentity,
    VoiceSessionPhase,
    VoiceSessionPhaseChanged,
    VoiceSessionReady,
    VoiceSessionRecoveryCompleted,
    VoiceSessionRecoveryFailed,
    VoiceSessionRecoveryStarted,
)
from server.voice_session.recovery import (
    SemanticResumePlan,
    SemanticResumePlanner,
    VoiceSessionEventTail,
    VoiceSessionSnapshot,
)

logger = logging.getLogger(__name__)


class VoiceSessionAdmissionRejected(Exception):
    def __init__(self, *, retry_after_ms: int | None = None) -> None:
        if retry_after_ms is not None and retry_after_ms < 0:
            raise ValueError("Voice Session retry delay must not be negative")
        super().__init__("Voice Session admission rejected")
        self.retry_after_ms = retry_after_ms


class VoiceSessionConversationUnavailable(Exception):
    """A safe boundary exception for failure to open the Realtime Conversation."""


class VoiceSessionContextRestoreFailed(Exception):
    """Safe boundary exception for an incomplete model-context restoration."""


class AdmissionLease(Protocol):
    async def release(self) -> None: ...


class VoiceSessionAdmissionController(Protocol):
    async def acquire(self, identity: VoiceSessionIdentity) -> AdmissionLease: ...


class VoiceSessionConversation(Protocol):
    async def close(self) -> None: ...


class VoiceSessionConversationFactory(Protocol):
    async def open(
        self,
        *,
        identity: VoiceSessionIdentity,
        profile: object,
    ) -> VoiceSessionConversation: ...


class VoiceSessionRecovery(Protocol):
    async def restore(
        self, *, target_thread_sequence: int
    ) -> tuple[int, str]: ...


class VoiceSessionRuntime:
    """Keep startup complexity behind one lifecycle/event interface."""

    def __init__(
        self,
        *,
        identity: VoiceSessionIdentity,
        profile: object,
        admission: VoiceSessionAdmissionController,
        conversations: VoiceSessionConversationFactory,
        close_timeout_s: float = 5.0,
        fast_resume_window_s: float = 5.0,
        event_tail_capacity: int = 256,
        recovery_deadline_s: float = 15.0,
    ) -> None:
        if close_timeout_s <= 0:
            raise ValueError("Voice Session close timeout must be positive")
        if fast_resume_window_s <= 0:
            raise ValueError("Voice Session fast-resume window must be positive")
        if recovery_deadline_s <= 0:
            raise ValueError("Voice Session recovery deadline must be positive")
        self._identity = identity
        self._profile = profile
        self._admission = admission
        self._conversations = conversations
        self._close_timeout_s = close_timeout_s
        self._fast_resume_window_s = fast_resume_window_s
        self._recovery_deadline_s = recovery_deadline_s
        self._phase = VoiceSessionPhase.INACTIVE
        self._events: asyncio.Queue[VoiceSessionEvent] = asyncio.Queue()
        self._event_tail = VoiceSessionEventTail(capacity=event_tail_capacity)
        self._session_sequence = 0
        self._client_audio_ready = asyncio.Event()
        self._input_epoch: str | None = None
        self._expected_input_epoch: str | None = None
        self._admission_lease: AdmissionLease | None = None
        self._conversation: VoiceSessionConversation | None = None
        self._quiesced = False
        self._quiesce_handle: asyncio.TimerHandle | None = None
        self._quiesce_task: asyncio.Task[None] | None = None
        self._recovery_deadline_handle: asyncio.TimerHandle | None = None
        self._recovery_deadline_task: asyncio.Task[None] | None = None

    @property
    def phase(self) -> VoiceSessionPhase:
        return self._phase

    @property
    def is_quiesced(self) -> bool:
        return self._quiesced

    def plan_semantic_resume(
        self,
        *,
        last_session_sequence: int,
        journal_sequence: int,
        generation: int,
        active_work_refs: tuple[str, ...] = (),
        pending_confirmation_id: str | None = None,
        playback_generation: int | None = None,
        played_position_samples: int | None = None,
    ) -> SemanticResumePlan:
        snapshot = VoiceSessionSnapshot(
            identity=self._identity,
            phase=self._phase,
            session_sequence=self._session_sequence,
            journal_sequence=journal_sequence,
            generation=generation,
            active_work_refs=active_work_refs,
            pending_confirmation_id=pending_confirmation_id,
            playback_generation=playback_generation,
            played_position_samples=played_position_samples,
        )
        return SemanticResumePlanner(event_tail=self._event_tail).plan(
            snapshot=snapshot,
            last_session_sequence=last_session_sequence,
        )

    async def start(self) -> None:
        if self._phase is not VoiceSessionPhase.INACTIVE:
            raise RuntimeError("Voice Session can start only from inactive")
        await self._transition(VoiceSessionPhase.STARTING)
        try:
            try:
                self._admission_lease = await self._admission.acquire(self._identity)
            except VoiceSessionAdmissionRejected as rejection:
                await self._fail_and_close(
                    code=VoiceSessionFailureCode.CAPACITY_EXHAUSTED,
                    retryable=True,
                    retry_after_ms=rejection.retry_after_ms,
                    safe_message="当前语音服务繁忙，请稍后重试。",
                )
                return
            try:
                self._conversation = await self._conversations.open(
                    identity=self._identity,
                    profile=self._profile,
                )
            except VoiceSessionConversationUnavailable:
                await self._release_admission()
                await self._fail_and_close(
                    code=VoiceSessionFailureCode.PROVIDER_UNAVAILABLE,
                    retryable=True,
                    safe_message="当前语音服务暂不可用，请稍后重试。",
                )
                return
            await self._client_audio_ready.wait()
            await self._transition(VoiceSessionPhase.ACTIVE)
            assert self._input_epoch is not None
            await self._emit(
                VoiceSessionReady(
                    event_id=str(uuid.uuid4()),
                    identity=self._identity,
                    session_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    input_epoch=self._input_epoch,
                )
            )
        except asyncio.CancelledError:
            await asyncio.shield(self.stop(reason="start_cancelled"))
            raise

    async def mark_client_audio_ready(self, *, input_epoch: str) -> None:
        if self._phase not in {
            VoiceSessionPhase.STARTING,
            VoiceSessionPhase.RECONNECTING,
        }:
            raise RuntimeError("client audio can become ready only during a barrier")
        if not input_epoch:
            raise ValueError("input epoch must be non-empty")
        if (
            self._expected_input_epoch is not None
            and input_epoch != self._expected_input_epoch
        ):
            raise ValueError("client audio epoch does not match the recovery target")
        self._input_epoch = input_epoch
        self._client_audio_ready.set()

    async def replace_active_input_epoch(self, *, input_epoch: str) -> None:
        """Release a negotiated device epoch without changing Session phase."""

        if self._phase is not VoiceSessionPhase.ACTIVE:
            raise RuntimeError("input device epoch can change only while active")
        if not input_epoch or input_epoch == self._input_epoch:
            raise ValueError("replacement input epoch must be new and identified")
        self._input_epoch = input_epoch
        await self._emit(
            VoiceSessionReady(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                input_epoch=input_epoch,
            )
        )

    async def detached(self) -> None:
        if self._phase is not VoiceSessionPhase.ACTIVE:
            raise RuntimeError("only an active Voice Session can detach")
        self._client_audio_ready.clear()
        self._input_epoch = None
        self._expected_input_epoch = None
        await self._transition(VoiceSessionPhase.RECONNECTING)
        loop = asyncio.get_running_loop()
        self._quiesce_handle = loop.call_later(
            self._fast_resume_window_s,
            self._start_quiesce_task,
        )
        self._recovery_deadline_handle = loop.call_later(
            self._recovery_deadline_s,
            self._start_recovery_deadline_task,
        )

    async def resume(
        self,
        *,
        target_thread_sequence: int,
        input_epoch: str,
        recovery: VoiceSessionRecovery,
    ) -> None:
        if self._phase is not VoiceSessionPhase.RECONNECTING:
            raise RuntimeError("Voice Session resume requires reconnecting phase")
        if target_thread_sequence < 0 or not input_epoch:
            raise ValueError(
                "Voice Session recovery target must be non-negative and identified"
            )
        await self._settle_quiesce(cancel_pending=True)
        self._expected_input_epoch = input_epoch
        await self._emit(
            VoiceSessionRecoveryStarted(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                target_thread_sequence=target_thread_sequence,
                input_epoch=input_epoch,
            )
        )
        resumed_from_quiesce = self._quiesced
        if self._quiesced:
            try:
                self._admission_lease = await self._admission.acquire(self._identity)
            except VoiceSessionAdmissionRejected as rejection:
                await self._emit_recovery_failed(
                    target_thread_sequence=target_thread_sequence,
                    code=VoiceSessionFailureCode.CAPACITY_EXHAUSTED,
                    retry_after_ms=rejection.retry_after_ms,
                    safe_message="当前语音服务繁忙，正在等待容量后重试。",
                )
                return
            try:
                self._conversation = await self._conversations.open(
                    identity=self._identity,
                    profile=self._profile,
                )
            except VoiceSessionConversationUnavailable:
                await self._release_admission()
                await self._emit_recovery_failed(
                    target_thread_sequence=target_thread_sequence,
                    code=VoiceSessionFailureCode.PROVIDER_UNAVAILABLE,
                    retry_after_ms=None,
                    safe_message="当前语音服务暂不可用，正在等待重试。",
                )
                return
            self._quiesced = False
        try:
            projected_through, projection_digest = await recovery.restore(
                target_thread_sequence=target_thread_sequence
            )
            if projected_through < target_thread_sequence or not projection_digest:
                raise VoiceSessionContextRestoreFailed()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not isinstance(error, VoiceSessionContextRestoreFailed):
                logger.exception(
                    "Voice Session recovery barrier failed: session=%s target=%s",
                    self._identity.voice_session_id,
                    target_thread_sequence,
                )
            await self._emit_recovery_failed(
                target_thread_sequence=target_thread_sequence,
                code=VoiceSessionFailureCode.CONTEXT_RESTORE_FAILED,
                retry_after_ms=None,
                safe_message="会话历史恢复失败，正在等待重试。",
            )
            if resumed_from_quiesce:
                await self._quiesce_realtime_resources()
            return
        await self._client_audio_ready.wait()
        if self._input_epoch != input_epoch:
            raise ValueError("client audio readiness does not match recovery epoch")
        await self._settle_recovery_deadline(cancel_pending=True)
        await self._transition(VoiceSessionPhase.ACTIVE)
        await self._emit(
            VoiceSessionRecoveryCompleted(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                target_thread_sequence=target_thread_sequence,
                projected_through=projected_through,
                projection_digest=projection_digest,
                input_epoch=input_epoch,
            )
        )
        await self._emit(
            VoiceSessionReady(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                input_epoch=input_epoch,
            )
        )
        self._expected_input_epoch = None

    async def stop(self, *, reason: str) -> None:
        if not reason:
            raise ValueError("Voice Session close reason must be non-empty")
        if self._phase is VoiceSessionPhase.CLOSED:
            return
        await self._settle_quiesce(cancel_pending=True)
        await self._settle_recovery_deadline(cancel_pending=True)
        if self._phase is not VoiceSessionPhase.STOPPING:
            await self._transition(VoiceSessionPhase.STOPPING)
        degraded_resources = await self._cleanup_resources()
        await self._transition(VoiceSessionPhase.CLOSED)
        await self._emit(
            VoiceSessionClosed(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                reason=reason,
                degraded_resources=degraded_resources,
            )
        )

    def events(self) -> AsyncIterator[VoiceSessionEvent]:
        return self._iterate_events()

    async def _iterate_events(self) -> AsyncIterator[VoiceSessionEvent]:
        while True:
            yield cast(VoiceSessionEvent, await self._events.get())

    async def _transition(self, to_phase: VoiceSessionPhase) -> None:
        from_phase = self._phase
        self._phase = to_phase
        await self._emit(
            VoiceSessionPhaseChanged(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                from_phase=from_phase,
                to_phase=to_phase,
            )
        )

    async def _emit(self, event: VoiceSessionEvent) -> None:
        self._event_tail.append(event)
        await self._events.put(event)

    async def _fail_and_close(
        self,
        *,
        code: VoiceSessionFailureCode,
        retryable: bool,
        safe_message: str,
        retry_after_ms: int | None = None,
    ) -> None:
        await self._emit(
            VoiceSessionFailed(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                code=code,
                phase=self._phase,
                retryable=retryable,
                retry_after_ms=retry_after_ms,
                session_disposition=VoiceSessionDisposition.CLOSE,
                safe_message=safe_message,
            )
        )
        await self.stop(reason=code.value)

    async def _emit_recovery_failed(
        self,
        *,
        target_thread_sequence: int,
        code: VoiceSessionFailureCode,
        retry_after_ms: int | None,
        safe_message: str,
        retryable: bool = True,
        disposition: VoiceSessionDisposition = VoiceSessionDisposition.KEEP_RECONNECTING,
    ) -> None:
        await self._emit(
            VoiceSessionRecoveryFailed(
                event_id=str(uuid.uuid4()),
                identity=self._identity,
                session_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                target_thread_sequence=target_thread_sequence,
                code=code,
                retryable=retryable,
                retry_after_ms=retry_after_ms,
                session_disposition=disposition,
                safe_message=safe_message,
            )
        )

    def _start_quiesce_task(self) -> None:
        self._quiesce_handle = None
        self._quiesce_task = asyncio.create_task(
            self._quiesce_realtime_resources(),
            name=f"voice-session-quiesce-{self._identity.voice_session_id}",
        )

    async def _settle_quiesce(self, *, cancel_pending: bool) -> None:
        if cancel_pending and self._quiesce_handle is not None:
            self._quiesce_handle.cancel()
            self._quiesce_handle = None
        task = self._quiesce_task
        if task is not None:
            await task
            if self._quiesce_task is task:
                self._quiesce_task = None

    async def _quiesce_realtime_resources(self) -> None:
        if self._phase is not VoiceSessionPhase.RECONNECTING or self._quiesced:
            return
        conversation = self._conversation
        if conversation is not None:
            quiesce = getattr(conversation, "quiesce", None)
            if quiesce is None:
                self._conversation = None
                await conversation.close()
            else:
                await quiesce()
        await self._release_admission()
        self._quiesced = True

    def _start_recovery_deadline_task(self) -> None:
        self._recovery_deadline_handle = None
        self._recovery_deadline_task = asyncio.create_task(
            self._recovery_deadline_exceeded(),
            name=f"voice-session-recovery-deadline-{self._identity.voice_session_id}",
        )

    async def _settle_recovery_deadline(self, *, cancel_pending: bool) -> None:
        if cancel_pending and self._recovery_deadline_handle is not None:
            self._recovery_deadline_handle.cancel()
            self._recovery_deadline_handle = None
        task = self._recovery_deadline_task
        current = asyncio.current_task()
        if task is not None and task is not current:
            if cancel_pending and not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._recovery_deadline_task is task:
                self._recovery_deadline_task = None

    async def _recovery_deadline_exceeded(self) -> None:
        if self._phase is not VoiceSessionPhase.RECONNECTING:
            return
        await self._emit_recovery_failed(
            target_thread_sequence=0,
            code=VoiceSessionFailureCode.RECOVERY_DEADLINE_EXCEEDED,
            retry_after_ms=None,
            safe_message="原会话恢复超时，请继续开启新会话。",
            retryable=False,
            disposition=VoiceSessionDisposition.CONTINUATION_REQUIRED,
        )
        await self.stop(reason=VoiceSessionFailureCode.RECOVERY_DEADLINE_EXCEEDED.value)

    async def _close_conversation(self) -> None:
        if self._conversation is None:
            return
        conversation, self._conversation = self._conversation, None
        await conversation.close()

    async def _cleanup_resources(self) -> tuple[str, ...]:
        tasks: dict[asyncio.Task[None], str] = {}
        if self._conversation is not None:
            conversation, self._conversation = self._conversation, None
            tasks[asyncio.create_task(conversation.close())] = "conversation"
        if self._admission_lease is not None:
            admission_lease, self._admission_lease = self._admission_lease, None
            tasks[asyncio.create_task(admission_lease.release())] = "admission"
        if not tasks:
            return ()

        done, pending = await asyncio.wait(tasks, timeout=self._close_timeout_s)
        degraded = {tasks[task] for task in pending}
        for task in done:
            if task.cancelled() or task.exception() is not None:
                degraded.add(tasks[task])
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return tuple(sorted(degraded))

    async def _release_admission(self) -> None:
        if self._admission_lease is None:
            return
        admission_lease, self._admission_lease = self._admission_lease, None
        await admission_lease.release()

    def _next_sequence(self) -> int:
        self._session_sequence += 1
        return self._session_sequence
