from __future__ import annotations

import asyncio

from server.voice_session import (
    VoiceSessionAdmissionRejected,
    VoiceSessionClosed,
    VoiceSessionContextRestoreFailed,
    VoiceSessionConversationUnavailable,
    VoiceSessionDisposition,
    VoiceSessionFailed,
    VoiceSessionFailureCode,
    VoiceSessionIdentity,
    VoiceSessionPhase,
    VoiceSessionPhaseChanged,
    VoiceSessionReady,
    VoiceSessionRecoveryCompleted,
    VoiceSessionRecoveryFailed,
    VoiceSessionRecoveryStarted,
    VoiceSessionRuntime,
)


class RecordingAdmissionLease:
    def __init__(self) -> None:
        self.released = False

    async def release(self) -> None:
        self.released = True


class RecordingAdmission:
    def __init__(self) -> None:
        self.acquired = asyncio.Event()
        self.identity: VoiceSessionIdentity | None = None
        self.lease = RecordingAdmissionLease()

    async def acquire(self, identity: VoiceSessionIdentity) -> RecordingAdmissionLease:
        self.identity = identity
        self.acquired.set()
        return self.lease


class RejectingAdmission:
    async def acquire(self, identity: VoiceSessionIdentity):
        del identity
        raise VoiceSessionAdmissionRejected(retry_after_ms=750)


class RecordingConversation:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class QuiesceableConversation(RecordingConversation):
    def __init__(self) -> None:
        super().__init__()
        self.quiesced = False

    async def quiesce(self) -> None:
        self.quiesced = True


class ReopeningConversationFactory:
    def __init__(self) -> None:
        self.conversations: list[QuiesceableConversation] = []
        self.opened = asyncio.Event()

    async def open(self, *, identity: VoiceSessionIdentity, profile: object):
        del identity, profile
        conversation = QuiesceableConversation()
        self.conversations.append(conversation)
        self.opened.set()
        return conversation


class ReacquiringAdmission:
    def __init__(self, *, reject_after: int | None = None) -> None:
        self.leases: list[RecordingAdmissionLease] = []
        self.reject_after = reject_after

    async def acquire(self, identity: VoiceSessionIdentity):
        del identity
        if self.reject_after is not None and len(self.leases) >= self.reject_after:
            raise VoiceSessionAdmissionRejected(retry_after_ms=900)
        lease = RecordingAdmissionLease()
        self.leases.append(lease)
        return lease


class RecordingConversationFactory:
    def __init__(self) -> None:
        self.opened = asyncio.Event()
        self.identity: VoiceSessionIdentity | None = None
        self.profile: object | None = None
        self.conversation = RecordingConversation()

    async def open(self, *, identity: VoiceSessionIdentity, profile: object):
        self.identity = identity
        self.profile = profile
        self.opened.set()
        return self.conversation


class HangingConversation(RecordingConversation):
    async def close(self) -> None:
        await asyncio.Event().wait()


class HangingConversationFactory(RecordingConversationFactory):
    def __init__(self) -> None:
        super().__init__()
        self.conversation = HangingConversation()


class BlockingRecovery:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.target_thread_sequence: int | None = None

    async def restore(self, *, target_thread_sequence: int):
        self.target_thread_sequence = target_thread_sequence
        self.started.set()
        await self.release.wait()
        return (target_thread_sequence, "projection-digest")


class FailingRecovery:
    async def restore(self, *, target_thread_sequence: int):
        del target_thread_sequence
        raise VoiceSessionContextRestoreFailed()


class CorruptControlRecovery:
    async def restore(self, *, target_thread_sequence: int):
        del target_thread_sequence
        raise ValueError("authorization projection mismatch")


class FailingConversationFactory:
    async def open(self, *, identity: VoiceSessionIdentity, profile: object):
        del identity, profile
        raise VoiceSessionConversationUnavailable()


def identity() -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )


async def test_session_becomes_active_only_after_all_startup_barriers() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    events = runtime.events()

    start_task = asyncio.create_task(runtime.start())

    starting = await anext(events)
    await asyncio.wait_for(admission.acquired.wait(), timeout=0.5)
    await asyncio.wait_for(conversations.opened.wait(), timeout=0.5)
    assert isinstance(starting, VoiceSessionPhaseChanged)
    assert starting.session_sequence == 1
    assert starting.from_phase is VoiceSessionPhase.INACTIVE
    assert starting.to_phase is VoiceSessionPhase.STARTING
    assert runtime.phase is VoiceSessionPhase.STARTING
    assert start_task.done() is False

    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await asyncio.wait_for(start_task, timeout=0.5)

    active = await anext(events)
    ready = await anext(events)
    assert isinstance(active, VoiceSessionPhaseChanged)
    assert active.session_sequence == 2
    assert active.from_phase is VoiceSessionPhase.STARTING
    assert active.to_phase is VoiceSessionPhase.ACTIVE
    assert isinstance(ready, VoiceSessionReady)
    assert ready.session_sequence == 3
    assert ready.input_epoch == "input-1"
    assert runtime.phase is VoiceSessionPhase.ACTIVE


async def test_capacity_rejection_is_a_safe_terminal_session_failure() -> None:
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=RejectingAdmission(),
        conversations=RecordingConversationFactory(),
    )
    events = runtime.events()

    await runtime.start()

    starting = await anext(events)
    failed = await anext(events)
    stopping = await anext(events)
    closed = await anext(events)
    assert isinstance(starting, VoiceSessionPhaseChanged)
    assert isinstance(failed, VoiceSessionFailed)
    assert failed.session_sequence == 2
    assert failed.code is VoiceSessionFailureCode.CAPACITY_EXHAUSTED
    assert failed.phase is VoiceSessionPhase.STARTING
    assert failed.retryable is True
    assert failed.retry_after_ms == 750
    assert failed.session_disposition is VoiceSessionDisposition.CLOSE
    assert failed.safe_message == "当前语音服务繁忙，请稍后重试。"
    assert isinstance(stopping, VoiceSessionPhaseChanged)
    assert stopping.to_phase is VoiceSessionPhase.STOPPING
    assert isinstance(closed, VoiceSessionPhaseChanged)
    assert closed.to_phase is VoiceSessionPhase.CLOSED
    assert runtime.phase is VoiceSessionPhase.CLOSED


async def test_conversation_open_failure_releases_admission_before_closing() -> None:
    admission = RecordingAdmission()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=FailingConversationFactory(),
    )
    events = runtime.events()

    await runtime.start()

    assert isinstance(await anext(events), VoiceSessionPhaseChanged)
    failed = await anext(events)
    assert isinstance(failed, VoiceSessionFailed)
    assert failed.code is VoiceSessionFailureCode.PROVIDER_UNAVAILABLE
    assert failed.retryable is True
    assert failed.session_disposition is VoiceSessionDisposition.CLOSE
    assert admission.lease.released is True
    assert runtime.phase is VoiceSessionPhase.CLOSED


async def test_stop_closes_runtime_resources_and_publishes_closed_event() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await asyncio.wait_for(conversations.opened.wait(), timeout=0.5)
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)

    await runtime.stop(reason="client_closed")

    stopping = await anext(events)
    closed_phase = await anext(events)
    closed = await anext(events)
    assert isinstance(stopping, VoiceSessionPhaseChanged)
    assert stopping.to_phase is VoiceSessionPhase.STOPPING
    assert isinstance(closed_phase, VoiceSessionPhaseChanged)
    assert closed_phase.to_phase is VoiceSessionPhase.CLOSED
    assert isinstance(closed, VoiceSessionClosed)
    assert closed.reason == "client_closed"
    assert closed.degraded_resources == ()
    assert conversations.conversation.closed is True
    assert admission.lease.released is True
    assert runtime.phase is VoiceSessionPhase.CLOSED


async def test_cancelled_start_closes_every_acquired_resource() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    start_task = asyncio.create_task(runtime.start())
    await asyncio.wait_for(conversations.opened.wait(), timeout=0.5)

    start_task.cancel()
    try:
        await start_task
    except asyncio.CancelledError:
        pass

    assert conversations.conversation.closed is True
    assert admission.lease.released is True
    assert runtime.phase is VoiceSessionPhase.CLOSED


async def test_stop_is_bounded_and_reports_degraded_resource_cleanup() -> None:
    admission = RecordingAdmission()
    conversations = HangingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
        close_timeout_s=0.01,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await asyncio.wait_for(conversations.opened.wait(), timeout=0.5)
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)

    await asyncio.wait_for(runtime.stop(reason="client_closed"), timeout=0.1)

    await anext(events)
    await anext(events)
    closed = await anext(events)
    assert isinstance(closed, VoiceSessionClosed)
    assert closed.degraded_resources == ("conversation",)
    assert admission.lease.released is True


async def test_recovery_returns_active_only_after_context_and_new_audio_are_ready() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)
    await runtime.detached()
    reconnecting = await anext(events)
    assert isinstance(reconnecting, VoiceSessionPhaseChanged)
    assert reconnecting.to_phase is VoiceSessionPhase.RECONNECTING

    recovery = BlockingRecovery()
    resume_task = asyncio.create_task(
        runtime.resume(
            target_thread_sequence=42,
            input_epoch="input-2",
            recovery=recovery,
        )
    )
    await recovery.started.wait()
    started = await anext(events)
    assert isinstance(started, VoiceSessionRecoveryStarted)
    await runtime.mark_client_audio_ready(input_epoch="input-2")
    assert runtime.phase is VoiceSessionPhase.RECONNECTING

    recovery.release.set()
    await resume_task

    active = await anext(events)
    completed = await anext(events)
    ready = await anext(events)
    assert isinstance(active, VoiceSessionPhaseChanged)
    assert active.to_phase is VoiceSessionPhase.ACTIVE
    assert isinstance(completed, VoiceSessionRecoveryCompleted)
    assert completed.projected_through == 42
    assert completed.projection_digest == "projection-digest"
    assert isinstance(ready, VoiceSessionReady)
    assert ready.input_epoch == "input-2"


async def test_detach_quiesces_realtime_resources_only_after_fast_resume_window() -> None:
    admission = ReacquiringAdmission()
    conversations = ReopeningConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
        fast_resume_window_s=0.02,
    )
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task

    await runtime.detached()

    assert runtime.is_quiesced is False
    assert conversations.conversations[0].quiesced is False
    assert admission.leases[0].released is False
    for _ in range(100):
        if runtime.is_quiesced:
            break
        await asyncio.sleep(0.001)

    assert runtime.is_quiesced is True
    assert conversations.conversations[0].quiesced is True
    assert admission.leases[0].released is True
    await runtime.stop(reason="test_complete")


async def test_quiesced_resume_reacquires_capacity_and_reopens_conversation() -> None:
    admission = ReacquiringAdmission()
    conversations = ReopeningConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
        fast_resume_window_s=0.001,
    )
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    await runtime.detached()
    for _ in range(100):
        if runtime.is_quiesced:
            break
        await asyncio.sleep(0.001)

    recovery = BlockingRecovery()
    resume_task = asyncio.create_task(
        runtime.resume(
            target_thread_sequence=3,
            input_epoch="input-2",
            recovery=recovery,
        )
    )
    await recovery.started.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-2")
    recovery.release.set()
    await resume_task

    assert runtime.phase is VoiceSessionPhase.ACTIVE
    assert runtime.is_quiesced is False
    assert len(admission.leases) == 2
    assert len(conversations.conversations) == 2
    await runtime.stop(reason="test_complete")


async def test_quiesced_resume_capacity_rejection_keeps_reconnecting() -> None:
    admission = ReacquiringAdmission(reject_after=1)
    conversations = ReopeningConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
        fast_resume_window_s=0.001,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)
    await runtime.detached()
    await anext(events)
    for _ in range(100):
        if runtime.is_quiesced:
            break
        await asyncio.sleep(0.001)

    await runtime.resume(
        target_thread_sequence=3,
        input_epoch="input-2",
        recovery=BlockingRecovery(),
    )

    started = await anext(events)
    assert isinstance(started, VoiceSessionRecoveryStarted)
    failed = await anext(events)
    assert isinstance(failed, VoiceSessionRecoveryFailed)
    assert failed.code is VoiceSessionFailureCode.CAPACITY_EXHAUSTED
    assert failed.retry_after_ms == 900
    assert failed.session_disposition is VoiceSessionDisposition.KEEP_RECONNECTING
    assert runtime.phase is VoiceSessionPhase.RECONNECTING
    assert runtime.is_quiesced is True
    await runtime.stop(reason="test_complete")


async def test_recovery_deadline_closes_old_session_and_requires_continuation() -> None:
    conversations = ReopeningConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=ReacquiringAdmission(),
        conversations=conversations,
        fast_resume_window_s=0.001,
        recovery_deadline_s=0.01,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)

    await runtime.detached()
    assert isinstance(await anext(events), VoiceSessionPhaseChanged)
    failed = await asyncio.wait_for(anext(events), timeout=0.1)

    assert isinstance(failed, VoiceSessionRecoveryFailed)
    assert failed.code is VoiceSessionFailureCode.RECOVERY_DEADLINE_EXCEEDED
    assert failed.retryable is False
    assert failed.session_disposition is VoiceSessionDisposition.CONTINUATION_REQUIRED
    for _ in range(3):
        await anext(events)
    assert runtime.phase is VoiceSessionPhase.CLOSED


async def test_active_device_epoch_switch_does_not_reconnect_voice_session() -> None:
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=RecordingAdmission(),
        conversations=conversations,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)

    await runtime.replace_active_input_epoch(input_epoch="input-device-2")

    ready = await anext(events)
    assert isinstance(ready, VoiceSessionReady)
    assert ready.input_epoch == "input-device-2"
    assert runtime.phase is VoiceSessionPhase.ACTIVE


async def test_runtime_semantic_resume_uses_tail_or_snapshot_at_cursor_gap() -> None:
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=RecordingAdmission(),
        conversations=conversations,
        event_tail_capacity=2,
    )
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task

    gap = runtime.plan_semantic_resume(
        last_session_sequence=0,
        journal_sequence=9,
        generation=4,
    )
    assert gap.snapshot is not None
    assert gap.snapshot.phase is VoiceSessionPhase.ACTIVE
    assert gap.snapshot.session_sequence == 3
    assert gap.snapshot.journal_sequence == 9
    assert gap.snapshot.generation == 4
    assert gap.events == ()

    incremental = runtime.plan_semantic_resume(
        last_session_sequence=1,
        journal_sequence=9,
        generation=4,
    )
    assert incremental.snapshot is None
    assert [event.session_sequence for event in incremental.events] == [2, 3]
    await runtime.stop(reason="test_complete")


async def test_context_restore_failure_stays_reconnecting_with_a_safe_event() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)
    await runtime.detached()
    await anext(events)

    await runtime.resume(
        target_thread_sequence=42,
        input_epoch="input-2",
        recovery=FailingRecovery(),
    )

    assert isinstance(await anext(events), VoiceSessionRecoveryStarted)
    failed = await anext(events)
    assert isinstance(failed, VoiceSessionRecoveryFailed)
    assert failed.code is VoiceSessionFailureCode.CONTEXT_RESTORE_FAILED
    assert failed.session_disposition is VoiceSessionDisposition.KEEP_RECONNECTING
    assert failed.safe_message == "会话历史恢复失败，正在等待重试。"
    assert runtime.phase is VoiceSessionPhase.RECONNECTING


async def test_control_recovery_exception_is_sanitized_and_stays_reconnecting() -> None:
    admission = RecordingAdmission()
    conversations = RecordingConversationFactory()
    runtime = VoiceSessionRuntime(
        identity=identity(),
        profile="cascaded-default",
        admission=admission,
        conversations=conversations,
    )
    events = runtime.events()
    start_task = asyncio.create_task(runtime.start())
    await conversations.opened.wait()
    await runtime.mark_client_audio_ready(input_epoch="input-1")
    await start_task
    for _ in range(3):
        await anext(events)
    await runtime.detached()
    await anext(events)

    await runtime.resume(
        target_thread_sequence=42,
        input_epoch="input-2",
        recovery=CorruptControlRecovery(),
    )

    assert isinstance(await anext(events), VoiceSessionRecoveryStarted)
    failed = await anext(events)
    assert isinstance(failed, VoiceSessionRecoveryFailed)
    assert failed.code is VoiceSessionFailureCode.CONTEXT_RESTORE_FAILED
    assert failed.session_disposition is VoiceSessionDisposition.KEEP_RECONNECTING
    assert runtime.phase is VoiceSessionPhase.RECONNECTING
