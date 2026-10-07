import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.realtime.in_memory import InMemoryRealtimeConversation
from server.realtime.protocol.commands import OutputStopFact, RecordOutputStop
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from server.realtime.speech.lifecycle import SpeechLifecycle
from server.transport.frames import AssistantSpeechCancelledFrame
from tests.realtime.test_output_stop_observations import request_stop
from tests.realtime.test_output_stop_protocol import audio_event
from tests.realtime.test_realtime_websocket_bridge import RecordingConversation, context


class StoredConversation(RecordingConversation):
    def __init__(self, store):
        super().__init__()
        self.lifecycle = SpeechLifecycle(store)

    async def send(self, command):
        if isinstance(command, RecordOutputStop):
            await self.lifecycle.record_output_stop(command.fact)
        await super().send(command)


def requested():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    return OutputStopFact(
        context=context(),
        stop_command_id="stop-1",
        output_epoch="epoch",
        speech_id="response:a",
        state="STOP_REQUESTED",
        reason="interrupted",
        requested_at=now,
        observed_at=now,
    )


def confirmed(fact):
    return replace(
        fact,
        state="STOP_CONFIRMED",
        received_at=fact.requested_at,
        receipt_outcome="queue_stopped",
        played_position_samples=1200,
    )


async def test_stop_facts_survive_replay_without_downgrading_confirmed_queue_evidence():
    store = InMemorySpeechDeliveryStore()
    request = requested()
    await store.record_output_stop(request)
    receipt = confirmed(request)
    await store.record_output_stop(receipt)
    await store.record_output_stop(request)  # Persistence can race after the wire receipt.
    assert await store.get_output_stop(context(), request.stop_command_id) == receipt
    assert await store.record_output_stop(receipt) == receipt


async def test_stop_fact_identity_is_scoped_and_terminal_states_cannot_be_rewritten():
    store = InMemorySpeechDeliveryStore()
    request = requested()
    await store.record_output_stop(request)
    with pytest.raises(ValueError):
        await store.record_output_stop(replace(request, output_epoch="other"))
    unknown = replace(request, state="STOP_UNKNOWN", failure_reason="receipt_deadline")
    await store.record_output_stop(unknown)
    with pytest.raises(ValueError):
        await store.record_output_stop(confirmed(request))
    for field in ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id"):
        other = replace(context(), **{field: "other"})
        assert await store.get_output_stop(other, request.stop_command_id) is None
        await store.record_output_stop(replace(request, context=other))
        assert await store.get_output_stop(other, request.stop_command_id) is not None
    assert await store.get_output_stop(context(), request.stop_command_id) == unknown


async def test_recording_command_crosses_actual_conversation_and_survives_restart():

    store = InMemorySpeechDeliveryStore()
    request = requested()
    first = InMemoryRealtimeConversation(context=context(), speech_deliveries=store)
    try:
        await first.send(
            RecordOutputStop(
                command_id="stop-request",
                idempotency_key="stop-request",
                context=context(),
                fact=request,
            )
        )
        await first.send(
            RecordOutputStop(
                command_id="stop-confirm",
                idempotency_key="stop-confirm",
                context=context(),
                fact=confirmed(request),
            )
        )
    finally:
        await first.close()
    reopened = InMemoryRealtimeConversation(context=context(), speech_deliveries=store)
    try:
        await reopened.send(
            RecordOutputStop(
                command_id="replay", idempotency_key="replay", context=context(), fact=request
            )
        )
        assert await store.get_output_stop(context(), request.stop_command_id) == confirmed(request)
        assert not store.output_stop_durable
    finally:
        await reopened.close()


async def test_stop_receipt_waits_for_fact_storage_before_allowing_new_audio():

    class GatedStore(InMemorySpeechDeliveryStore):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def record_output_stop(self, fact):
            if fact.state == "STOP_CONFIRMED":
                self.entered.set()
                await self.release.wait()
            return await super().record_output_stop(fact)

    store = GatedStore()
    conversation = StoredConversation(store)
    bridge, transport, receipt = await request_stop(lambda event: None, conversation=conversation)
    receiving = asyncio.create_task(bridge.handle_inbound(receipt))
    sending = asyncio.create_task(bridge.handle_event(audio_event("next", 4)))
    try:
        await asyncio.wait_for(store.entered.wait(), 0.5)
        assert not receiving.done() and not sending.done()
        assert not any(
            getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames
        )
        store.release.set()
        await asyncio.wait_for(receiving, 1)
        await asyncio.wait_for(sending, 1)
        fact = await store.get_output_stop(context(), receipt.stop_command_id)
        assert fact is not None and fact.state == "STOP_CONFIRMED"
        assert fact.context.turn_id == "original-turn" and fact.context.generation == 3
        assert fact.played_position_samples == 1200
        assert transport.frames[-1].speech_id == "response:next"
    finally:
        store.release.set()
        await bridge.close()
        await asyncio.gather(receiving, sending, return_exceptions=True)


@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_failed_confirmation_storage_never_grants_handoff(failure):

    class FailedStore(InMemorySpeechDeliveryStore):
        async def record_output_stop(self, fact):
            if fact.state == "STOP_CONFIRMED":
                if failure == "error":
                    raise RuntimeError("database unavailable")
                await asyncio.Event().wait()
            return await super().record_output_stop(fact)

    store = FailedStore()
    observed = []
    bridge, transport, receipt = await request_stop(
        observed.append, conversation=StoredConversation(store), timeout=30
    )
    try:
        with pytest.raises((RuntimeError, TimeoutError)):
            await bridge.handle_inbound(receipt)
        await bridge.handle_event(audio_event("next", 4))
        snapshot = bridge.output_stop_snapshot()[0]
        assert snapshot.state == "STOP_CONFIRMED"
        assert (
            snapshot.reason
            == f"stop_fact_persistence_{'failed' if failure == 'error' else 'deadline'}"
        )
        assert not any(
            getattr(frame, "speech_id", None) == "response:next" for frame in transport.frames
        )
        assert [event.phase for event in observed].count("handoff_failed") == 1
        assert not any(event.phase == "handoff_ready" for event in observed)
        fact = await store.get_output_stop(context(), receipt.stop_command_id)
        assert fact is not None and fact.state == "STOP_REQUESTED"
    finally:
        await bridge.close()


async def test_stop_wire_delivery_does_not_wait_for_request_storage_and_close_records_unknown():

    class GatedStore(InMemorySpeechDeliveryStore):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def record_output_stop(self, fact):
            if fact.state == "STOP_REQUESTED":
                self.entered.set()
                await self.release.wait()
            return await super().record_output_stop(fact)

    store = GatedStore()
    bridge, transport, receipt = await request_stop(
        lambda event: None, conversation=StoredConversation(store)
    )
    try:
        await asyncio.wait_for(store.entered.wait(), 0.1)
        assert isinstance(transport.frames[-1], AssistantSpeechCancelledFrame)
        assert not store.release.is_set()
        await asyncio.wait_for(bridge.close(), 0.5)
        fact = await store.get_output_stop(context(), receipt.stop_command_id)
        assert (
            fact is not None
            and fact.state == "STOP_UNKNOWN"
            and fact.failure_reason == "session_closed"
        )
        store.release.set()
        await asyncio.sleep(0)
        assert await store.get_output_stop(context(), receipt.stop_command_id) == fact
    finally:
        store.release.set()
        await bridge.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "invalid"},
        {"played_position_samples": 1},
        {"received_at": datetime(2026, 10, 7, tzinfo=UTC).replace(tzinfo=None)},
        {"state": "STOP_CONFIRMED"},
        {"state": "STOP_UNKNOWN", "failure_reason": "deadline", "played_position_samples": 0},
    ],
)
def test_stop_fact_rejects_inconsistent_evidence(changes):
    with pytest.raises(ValueError):
        replace(requested(), **changes)


async def test_terminal_stop_conflicts_preserve_first_confirmation():
    store = InMemorySpeechDeliveryStore()
    receipt = confirmed(requested())
    await store.record_output_stop(receipt)
    with pytest.raises(ValueError):
        await store.record_output_stop(replace(receipt, played_position_samples=1))
    assert await store.get_output_stop(context(), receipt.stop_command_id) == receipt


@pytest.mark.parametrize("wrappers", ["none", "tools", "tools_and_agents"])
@pytest.mark.parametrize("has_receipt", [False, True])
async def test_managed_close_saves_terminal_fact_while_request_ack_is_blocked(
    wrappers, has_receipt
):
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.registry import ActiveRealtimeConversations
    from server.realtime.runtime import RealtimeRuntimeFactory

    class DelayedRequestStore(InMemorySpeechDeliveryStore):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()

        async def record_output_stop(self, fact):
            saved = await super().record_output_stop(fact)
            if fact.state == "STOP_REQUESTED":
                self.entered.set()
                await asyncio.Event().wait()
            return saved

    store = DelayedRequestStore()

    class Engine:
        async def open(self, **kwargs):
            return InMemoryRealtimeConversation(context=kwargs["context"], speech_deliveries=store)

    factory = RealtimeRuntimeFactory(
        engine=Engine(),
        journal=InMemoryConversationJournal(),
        speech_deliveries=store,
        active_conversations=ActiveRealtimeConversations(),
        tool_control_handler_factory=(lambda: object()) if wrappers != "none" else None,
        agent_task_supervisor=object() if wrappers == "tools_and_agents" else None,
        delegation_request_factory=(lambda event: None) if wrappers == "tools_and_agents" else None,
    )
    managed = await factory.open(context=context(), profile=None)
    bridge = None
    receiving = None
    try:
        bridge, _, receipt = await request_stop(lambda event: None, conversation=managed)
        await asyncio.wait_for(store.entered.wait(), 0.5)
        if has_receipt:
            receiving = asyncio.create_task(bridge.handle_inbound(receipt))
            async with asyncio.timeout(0.5):
                while bridge.output_stop_snapshot()[0].state != "STOP_CONFIRMED":
                    await asyncio.sleep(0)
        await asyncio.wait_for(bridge.close(), 0.5)
        fact = await store.get_output_stop(context(), receipt.stop_command_id)
        assert fact is not None
        assert fact.state == ("STOP_CONFIRMED" if has_receipt else "STOP_UNKNOWN")
        assert fact.context.turn_id == "original-turn"
        assert fact.failure_reason == (None if has_receipt else "session_closed")
    finally:
        if bridge is not None:
            await bridge.close()
        if receiving is not None:
            await asyncio.gather(receiving, return_exceptions=True)
        await managed.close()


async def test_stop_fact_deletion_is_exact_session_scope_across_devices():
    store = InMemorySpeechDeliveryStore()
    request = requested()
    contexts = [request.context, replace(request.context, device_id="second-device")]
    others = [
        replace(request.context, **{field: "other"})
        for field in ("tenant_id", "user_id", "thread_id", "voice_session_id")
    ]
    for ctx in contexts + others:
        await store.record_output_stop(replace(request, context=ctx))
    assert (
        await store.delete_output_stop_facts(
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
            thread_id=request.context.thread_id,
            voice_session_id=request.context.voice_session_id,
        )
        == 2
    )
    for ctx in contexts:
        assert await store.get_output_stop(ctx, request.stop_command_id) is None
    for ctx in others:
        assert await store.get_output_stop(ctx, request.stop_command_id) is not None
    with pytest.raises(ValueError):
        await store.delete_output_stop_facts(
            tenant_id="", user_id="u", thread_id="t", voice_session_id="s"
        )


@pytest.mark.parametrize("wrappers", ["none", "tools", "tools_and_agents"])
async def test_stop_facts_cross_cascaded_engine_and_all_decorators(wrappers):
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.registry import ActiveRealtimeConversations
    from server.realtime.runtime import RealtimeRuntimeFactory
    from tests.realtime.test_reply_revision_production_delivery import open_core

    store = InMemorySpeechDeliveryStore()

    class Engine:
        async def open(self, **kwargs):
            return await open_core(speech_deliveries=store, interaction_context=kwargs["context"])

    factory = RealtimeRuntimeFactory(
        engine=Engine(),
        journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
        tool_control_handler_factory=(lambda: object()) if wrappers != "none" else None,
        agent_task_supervisor=object() if wrappers == "tools_and_agents" else None,
        delegation_request_factory=(lambda event: None) if wrappers == "tools_and_agents" else None,
    )
    managed = await factory.open(context=context(), profile=None)
    request = requested()
    try:
        for index, fact in enumerate((request, confirmed(request), request)):
            await managed.send(
                RecordOutputStop(
                    command_id=f"fact-{index}",
                    idempotency_key=f"fact-{index}",
                    context=fact.context,
                    fact=fact,
                )
            )
        assert await store.get_output_stop(request.context, request.stop_command_id) == confirmed(
            request
        )
    finally:
        await managed.close()


async def test_managed_stop_fact_storage_survives_closed_delegate_during_reconfiguration():
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.registry import ActiveRealtimeConversations
    from server.realtime.runtime import RealtimeRuntimeFactory

    store = InMemorySpeechDeliveryStore()
    entered, release = asyncio.Event(), asyncio.Event()

    class Engine:
        opens = 0

        async def open(self, **kwargs):
            self.opens += 1
            if self.opens == 2:
                entered.set()
                await release.wait()
            return InMemoryRealtimeConversation(context=kwargs["context"], speech_deliveries=store)

    managed = await RealtimeRuntimeFactory(
        engine=Engine(),
        journal=InMemoryConversationJournal(),
        speech_deliveries=store,
        active_conversations=ActiveRealtimeConversations(),
    ).open(context=context(), profile=None)
    bridge, _, receipt = await request_stop(lambda event: None, conversation=managed)
    reconfiguring = None
    receiving = None
    try:
        async with asyncio.timeout(0.5):
            while await store.get_output_stop(context(), receipt.stop_command_id) is None:
                await asyncio.sleep(0)
        reconfiguring = asyncio.create_task(managed.reconfigure(profile=None))
        await asyncio.wait_for(entered.wait(), 0.5)
        receiving = asyncio.create_task(bridge.handle_inbound(receipt))
        async with asyncio.timeout(0.5):
            while (
                await store.get_output_stop(context(), receipt.stop_command_id)
            ).state != "STOP_CONFIRMED":
                await asyncio.sleep(0)
        assert not receiving.done()  # Actor projection still waits for the replacement.
        recorded = requested()
        other = replace(
            recorded, context=replace(recorded.context, user_id="other"), stop_command_id="other"
        )
        with pytest.raises(ValueError, match="scope"):
            await managed.send(
                RecordOutputStop(
                    command_id="other", idempotency_key="other", context=other.context, fact=other
                )
            )
        assert await store.get_output_stop(other.context, "other") is None
        bridge.begin_close()
        receiving.cancel()
        await asyncio.gather(receiving, return_exceptions=True)
        await bridge.close()
        fact = await store.get_output_stop(context(), receipt.stop_command_id)
        assert fact.state == "STOP_CONFIRMED" and fact.played_position_samples == 1200
        assert fact.context.turn_id == "original-turn"
        assert bridge.output_stop_snapshot()[0].reason == "session_closed"
    finally:
        bridge.begin_close()
        if receiving is not None:
            receiving.cancel()
            await asyncio.gather(receiving, return_exceptions=True)
        release.set()
        if reconfiguring is not None:
            await asyncio.gather(reconfiguring, return_exceptions=True)
        await bridge.close()
        await managed.close()


@pytest.mark.parametrize("cooperative", [True, False])
@pytest.mark.parametrize("termination", ["close", "fatal_reconfigure"])
async def test_managed_close_keeps_session_owned_until_inflight_stop_writes_settle(
    cooperative, termination
):
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.registry import ActiveRealtimeConversations, SessionHistoryDeletionConflict
    from server.realtime.runtime import RealtimeRuntimeFactory

    entered, release = asyncio.Event(), asyncio.Event()

    class GatedStore(InMemorySpeechDeliveryStore):
        async def record_output_stop(self, fact):
            if fact.state == "STOP_CONFIRMED":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    if cooperative:
                        raise
                    await release.wait()
            return await super().record_output_stop(fact)

    store = GatedStore()
    active = ActiveRealtimeConversations()

    class Engine:
        opens = 0

        async def open(self, **kwargs):
            self.opens += 1
            if self.opens > 1:
                raise RuntimeError("injected reconfiguration failure")
            return InMemoryRealtimeConversation(context=kwargs["context"], speech_deliveries=store)

    managed = await RealtimeRuntimeFactory(
        engine=Engine(),
        journal=InMemoryConversationJournal(),
        speech_deliveries=store,
        active_conversations=active,
    ).open(context=context(), profile=None)
    request = requested()
    await store.record_output_stop(request)
    writing = asyncio.create_task(
        managed.send(
            RecordOutputStop(
                command_id="confirm",
                idempotency_key="confirm",
                context=context(),
                fact=confirmed(request),
            )
        )
    )
    scope = (context().tenant_id, context().user_id, context().voice_session_id)
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        if termination == "fatal_reconfigure":
            with pytest.raises(ExceptionGroup, match="reconfiguration and rollback"):
                await asyncio.wait_for(managed.reconfigure(profile=None), 0.5)
            await managed.close()
        else:
            await asyncio.wait_for(managed.close(), 0.5)
        if not cooperative:
            with (
                pytest.raises(SessionHistoryDeletionConflict),
                active.session_deletion_guard([scope]),
            ):
                pass
        else:
            assert writing.done()
        release.set()
        await asyncio.gather(writing, return_exceptions=True)
        with active.session_deletion_guard([scope]):
            await store.delete_output_stop_facts(
                tenant_id=context().tenant_id,
                user_id=context().user_id,
                thread_id=context().thread_id,
                voice_session_id=context().voice_session_id,
            )
        assert await store.get_output_stop(context(), request.stop_command_id) is None
    finally:
        release.set()
        await asyncio.gather(writing, return_exceptions=True)
        await managed.close()


@pytest.mark.parametrize("phase", ["before_reconfigure", "during_reconfigure", "close"])
async def test_saved_stop_notification_cannot_cross_delegate_replacement(phase):
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.registry import ActiveRealtimeConversations
    from server.realtime.runtime import RealtimeRuntimeFactory

    saving, release_save = asyncio.Event(), asyncio.Event()
    opening, release_open = asyncio.Event(), asyncio.Event()

    class Store(InMemorySpeechDeliveryStore):
        async def record_output_stop(self, fact):
            saving.set()
            try:
                await release_save.wait()
            except asyncio.CancelledError:
                # Exercise retained ownership of a noncooperative storage write.
                await release_save.wait()
            return await super().record_output_stop(fact)

    store, delegates = Store(), []

    class Delegate(InMemoryRealtimeConversation):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.stops = []

        async def observe_saved_output_stop(self, fact):
            self.stops.append(fact)

    class Engine:
        async def open(self, **kwargs):
            if delegates:
                opening.set()
                await release_open.wait()
            delegate = Delegate(context=kwargs["context"], speech_deliveries=store)
            delegates.append(delegate)
            return delegate

    managed = await RealtimeRuntimeFactory(engine=Engine(), journal=InMemoryConversationJournal(),
        speech_deliveries=store, active_conversations=ActiveRealtimeConversations()).open(context=context(), profile=None)
    writing = reconfiguring = None
    fact = requested()

    def write():
        return asyncio.create_task(managed.send(RecordOutputStop(command_id="fact", idempotency_key="fact",
            context=fact.context, fact=fact)))

    try:
        if phase in {"before_reconfigure", "close"}:
            writing = write()
            await asyncio.wait_for(saving.wait(), 1)
        if phase == "close":
            await managed.close()
        else:
            reconfiguring = asyncio.create_task(managed.reconfigure(profile=None))
            await asyncio.wait_for(opening.wait(), 1)
            if phase == "during_reconfigure":
                writing = write()
                await asyncio.wait_for(saving.wait(), 1)
            release_open.set()
            await reconfiguring
        release_save.set()
        await writing
        assert await store.get_output_stop(fact.context, fact.stop_command_id) == fact
        assert all(not delegate.stops for delegate in delegates)
    finally:
        release_save.set()
        release_open.set()
        await asyncio.gather(*(task for task in (writing, reconfiguring) if task is not None), return_exceptions=True)
        await managed.close()


@pytest.mark.parametrize("operation_sequence", [None, 1, 512])
def test_postgres_stop_payload_roundtrips_optional_server_order(operation_sequence):
    import json

    from server.persistence.postgres.speech_delivery import _stop_fact, _stop_json
    from server.realtime.scope import conversation_scope

    fact = replace(confirmed(requested()), operation_sequence=operation_sequence)
    payload = json.loads(_stop_json(fact))
    if operation_sequence is None:
        payload.pop("operation_sequence")  # Old stored rows remain readable.
    names = ("tenant_id", "user_id", "device_id", "voice_session_id", "thread_id")
    row = dict(zip(names, conversation_scope(fact.context), strict=True))
    row.update(stop_command_id=fact.stop_command_id, state=fact.state, payload=payload)
    assert _stop_fact(row) == fact


@pytest.mark.parametrize("operation_sequence", [0, -1, True, 1.5, "1"])
def test_stop_fact_rejects_invalid_server_operation_order(operation_sequence):
    with pytest.raises(ValueError, match="operation sequence"):
        replace(requested(), operation_sequence=operation_sequence)


@pytest.mark.parametrize("stage", ["cancel_output", "close_delegate"])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_reconfiguration_barrier_failure_closes_instead_of_leaving_a_silent_observer(stage, failure):
    from server.conversation_journal import InMemoryConversationJournal
    from server.realtime.protocol.commands import CancelResponse
    from server.realtime.protocol.events import RealtimeCapabilityFailed
    from server.realtime.registry import ActiveRealtimeConversations, SessionHistoryDeletionConflict
    from server.realtime.runtime import RealtimeRuntimeFactory

    entered, release = asyncio.Event(), asyncio.Event()
    recovery_entered, recovery_cancelled = asyncio.Event(), asyncio.Event()

    class Recovery:
        async def recovery_profile(self, **kwargs):
            recovery_entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                recovery_cancelled.set()
                raise

    store, delegates = InMemorySpeechDeliveryStore(), []

    async def fail():
        entered.set()
        if failure == "error":
            raise RuntimeError("controlled reconfiguration barrier failure")
        await release.wait()

    class Delegate(InMemoryRealtimeConversation):
        close_attempts = 0

        async def events(self):
            yield RealtimeCapabilityFailed(event_id="controlled-recovery", context=context(),
                conversation_sequence=1, occurred_at=datetime.now(UTC), capability="llm", error="controlled failure")
            async for event in super().events():
                yield event

        async def send(self, command):
            if stage == "cancel_output" and isinstance(command, CancelResponse):
                await fail()
            await super().send(command)

        async def close(self):
            self.close_attempts += 1
            if stage == "close_delegate" and self.close_attempts == 1:
                await fail()
            await super().close()

    class Engine:
        async def open(self, **kwargs):
            delegate = Delegate(context=kwargs["context"], speech_deliveries=store)
            delegates.append(delegate)
            return delegate

    active = ActiveRealtimeConversations()
    managed = await RealtimeRuntimeFactory(engine=Engine(), journal=InMemoryConversationJournal(),
        speech_deliveries=store, active_conversations=active, failure_recovery=Recovery()).open(context=context(), profile=None)
    await asyncio.wait_for(recovery_entered.wait(), 1)
    if stage == "cancel_output":
        managed._mark_output_started(response_id="a")
    reconfiguring = asyncio.create_task(managed.reconfigure(profile=None))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if failure == "cancel":
            reconfiguring.cancel()
        with pytest.raises(RuntimeError if failure == "error" else asyncio.CancelledError):
            await reconfiguring
        assert managed._closed, "a failed barrier cannot leave a live handle without stop observation"
        if stage == "close_delegate":
            with pytest.raises(RuntimeError, match="delegate close was not confirmed"):
                await asyncio.wait_for(managed.close(), 1)
            assert not managed._close_completed
            scope = (context().tenant_id, context().user_id, context().voice_session_id)
            with pytest.raises(SessionHistoryDeletionConflict), active.session_deletion_guard([scope]):
                pass
        else:
            await asyncio.wait_for(managed.close(), 1)
            assert delegates[0]._closed and managed._close_completed
        assert managed._recovery_task.done() and recovery_cancelled.is_set()
        assert len(delegates) == 1
        fact = requested()
        with pytest.raises(RuntimeError, match="closed"):
            await managed.send(RecordOutputStop(command_id="late", idempotency_key="late", context=fact.context, fact=fact))
        assert await store.get_output_stop(fact.context, fact.stop_command_id) is None
    finally:
        release.set()
        reconfiguring.cancel()
        await asyncio.gather(reconfiguring, return_exceptions=True)
        await delegates[0].close()  # Test-owned underlying fake cleanup after an uncertain wrapper close.
        await asyncio.gather(managed.close(), return_exceptions=True)
