from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from server.agent_session.driver_protocol import WorkspaceMode
from server.agent_session.in_memory_driver_v2 import InMemoryAgentDriverV2
from server.agent_session.supervisor import AgentTaskSupervisor
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    DelegationRequest,
)
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    JournalScope,
    SpokenContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import (
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
)
from server.persistence.in_memory import InMemoryPersistence
from server.realtime import (
    ActiveRealtimeConversations,
    AgentDelegationRequested,
    AgentDelegationRequestProposed,
    CancelResponse,
    InterruptedContextPolicy,
    ItemProjected,
    PlaybackPrecision,
    ProjectCommittedItem,
    RealtimeCapabilityFailed,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseStarted,
    SpeechContextPolicy,
    ToolRequested,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol.events import InputTranscriptCompleted
from server.realtime.runtime import RealtimeRuntimeFactory
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
)
from server.tools.canonical import LatencyClass
from server.tools.control import ToolControlResult


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


class RecordingConversation:
    def __init__(self) -> None:
        self.closed = False
        self.commands = []
        self.event_queue = asyncio.Queue()

    async def send(self, command) -> None:
        self.commands.append(command)
        if isinstance(command, ProjectCommittedItem):
            await self.event_queue.put(
                ItemProjected(
                    event_id=f"projected:{command.item.item_id}",
                    context=command.context,
                    conversation_sequence=command.item.sequence,
                    occurred_at=datetime.now(UTC),
                    item_id=command.item.item_id,
                    thread_sequence=command.item.sequence,
                    thread_version=command.item.thread_version,
                )
            )
        elif isinstance(command, CancelResponse):
            await self.event_queue.put(
                ResponseCancelled(
                    event_id=f"cancelled:{command.response_id}",
                    context=replace(command.context, response_id=command.response_id),
                    conversation_sequence=2,
                    occurred_at=datetime.now(UTC),
                    response_id=command.response_id,
                    response_sequence=1,
                    reason=command.reason,
                )
            )

    async def events(self):
        while True:
            event = await self.event_queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True
        await self.event_queue.put(None)


class RecordingEngine:
    def __init__(self) -> None:
        self.conversations = []
        self.profile = None
        self.opened_profiles = []
        self.second_opened = asyncio.Event()

    async def open(self, *, context: InteractionContext, profile):
        del context
        self.profile = profile
        self.opened_profiles.append(profile)
        conversation = RecordingConversation()
        self.conversations.append(conversation)
        if len(self.conversations) >= 2:
            self.second_opened.set()
        return conversation

    @property
    def conversation(self) -> RecordingConversation:
        return self.conversations[-1]


class ImmediateToolHandler:
    async def handle(self, action, cancellation) -> ToolControlResult:
        assert cancellation.is_cancelled is False
        return ToolControlResult(
            call_id=action.call_id,
            success=True,
            model_output="12:30",
        )


class RejectingProfileEngine(RecordingEngine):
    async def open(self, *, context: InteractionContext, profile):
        if profile == "profile-b":
            self.opened_profiles.append(profile)
            raise RuntimeError("profile-b cannot open")
        return await super().open(context=context, profile=profile)


async def test_runtime_factory_wraps_registers_and_unregisters_one_conversation() -> None:
    engine = RecordingEngine()
    active = ActiveRealtimeConversations()
    factory = RealtimeRuntimeFactory(
        engine=engine,
        journal=InMemoryConversationJournal(),
        active_conversations=active,
    )

    conversation = await factory.open(context=context(), profile=None)

    registered = active.resolve(context())
    assert registered is not None
    assert registered.conversation is conversation
    assert engine.profile is None

    await conversation.close()

    assert engine.conversation.closed is True
    assert active.resolve(context()) is None


async def test_automatic_response_request_is_visible_to_runtime_observability() -> None:
    telemetry_runtime = RuntimeTelemetry(
        InMemoryTelemetryStore(), flush_interval_s=0.01
    )
    await telemetry_runtime.start()
    telemetry = telemetry_runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    engine = RecordingEngine()
    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
        observer=RealtimeTelemetryObserver(telemetry),
    ).open(context=context(), profile=None)
    await engine.conversation.event_queue.put(
        InputTranscriptCompleted(
            event_id="input-complete",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            text="你好",
            transcript_revision=1,
            provider_endpoint_observed=True,
        )
    )

    while not any(
        isinstance(command, RequestResponse)
        for command in engine.conversation.commands
    ):
        await asyncio.sleep(0)
    request = next(
        command
        for command in engine.conversation.commands
        if isinstance(command, RequestResponse)
    )
    response_context = replace(request.context, response_id=request.response_id)
    await engine.conversation.event_queue.put(
        ResponseStarted(
            event_id="response-started",
            context=response_context,
            conversation_sequence=2,
            occurred_at=datetime.now(UTC),
            response_id=request.response_id,
            response_sequence=1,
        )
    )
    await engine.conversation.event_queue.put(
        ResponseCompleted(
            event_id="response-completed",
            context=response_context,
            conversation_sequence=3,
            occurred_at=datetime.now(UTC),
            response_id=request.response_id,
            response_sequence=2,
        )
    )
    while True:
        await telemetry_runtime.flush()
        detail = await telemetry_runtime.diagnostics.session_detail("voice-1")
        if detail is not None and any(
            record.name == "turn.total" for record in detail.events
        ):
            break
        await asyncio.sleep(0)

    assert detail is not None
    assert any(
        record.name == "realtime.response_requested" for record in detail.events
    )
    assert all(
        record.duration_ms is not None
        for record in detail.events
        if record.name in {"brain.response_started", "turn.total"}
    )
    await conversation.close()
    await telemetry_runtime.close()


async def test_runtime_factory_executes_and_projects_tool_requests() -> None:
    engine = RecordingEngine()
    journal = InMemoryConversationJournal()
    factory = RealtimeRuntimeFactory(
        engine=engine,
        journal=journal,
        active_conversations=ActiveRealtimeConversations(),
        tool_control_handler_factory=ImmediateToolHandler,
    )
    conversation = await factory.open(context=context(), profile=None)
    events = conversation.events()
    tool_context = replace(
        context(), response_id="response-1", call_id="call-1"
    )
    await engine.conversation.event_queue.put(
        ToolRequested(
            event_id="tool-1",
            context=tool_context,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1.0.0",
            arguments={},
            latency=LatencyClass.FAST,
        )
    )

    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ToolRequested)
    while not engine.conversation.commands:
        await asyncio.sleep(0)

    projected = engine.conversation.commands[-1]
    assert isinstance(projected, ProjectCommittedItem)
    assert projected.item.kind is ConversationItemKind.TOOL_RESULT
    items = await journal.read(JournalScope.from_context(context()))
    assert [item.kind for item in items] == [ConversationItemKind.TOOL_RESULT]
    await conversation.close()


async def test_runtime_factory_commits_delegation_through_supervisor() -> None:
    engine = RecordingEngine()
    persistence = InMemoryPersistence()
    supervisor = AgentTaskSupervisor(
        persistence=persistence,
        drivers={"codex": InMemoryAgentDriverV2(driver_kind="codex")},
    )

    def request_factory(event: AgentDelegationRequestProposed) -> DelegationRequest:
        return DelegationRequest(
            delegation_request_id=event.delegation_request_id,
            selection_plan=AgentSelectionPlan(
                plan_id="voice-runtime-codex",
                version=1,
                primary=AgentCandidate("codex"),
            ),
            instruction=event.instruction,
            context=event.context,
            workspace_root="/workspace",
            workspace_mode=WorkspaceMode.READ_ONLY,
        )

    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=persistence.journal,
        active_conversations=ActiveRealtimeConversations(),
        agent_task_supervisor=supervisor,
        delegation_request_factory=request_factory,
    ).open(context=context(), profile=None)
    events = conversation.events()
    await engine.conversation.event_queue.put(
        AgentDelegationRequestProposed(
            event_id="proposal-1",
            context=replace(context(), response_id="response-1"),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
            delegation_request_id="delegation-1",
            instruction="Inspect the project",
            agent_name="codex",
        )
    )

    accepted = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(accepted, AgentDelegationRequested)
    projected = engine.conversation.commands[-1]
    assert isinstance(projected, ProjectCommittedItem)
    assert projected.item.kind is ConversationItemKind.DELEGATION_REQUESTED
    await conversation.close()
    await supervisor.shutdown()


async def test_second_runtime_cannot_replace_an_active_conversation_scope() -> None:
    active = ActiveRealtimeConversations()
    first_engine = RecordingEngine()
    second_engine = RecordingEngine()
    first = await RealtimeRuntimeFactory(
        engine=first_engine,
        journal=InMemoryConversationJournal(),
        active_conversations=active,
    ).open(context=context(), profile=None)

    with pytest.raises(ValueError, match="already active"):
        await RealtimeRuntimeFactory(
            engine=second_engine,
            journal=InMemoryConversationJournal(),
            active_conversations=active,
        ).open(context=context(), profile=None)

    assert second_engine.conversation.closed is True
    assert active.resolve(context()).conversation is first
    await first.close()


async def test_reconfigure_keeps_public_handle_and_replays_journal_before_routing() -> None:
    journal = InMemoryConversationJournal()
    committed = await journal.append(
        ConversationItemDraft(
            item_id="user-1",
            context=context(),
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMPLETED,
            producer="test",
            content=(TextContent("already committed"),),
        )
    )
    engine = RecordingEngine()
    active = ActiveRealtimeConversations()
    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=journal,
        active_conversations=active,
    ).open(context=context(), profile="profile-a")

    assert isinstance(engine.conversations[0].commands[0], ProjectCommittedItem)
    assert engine.conversations[0].commands[0].item == committed.item

    await conversation.reconfigure(profile="profile-b")

    assert engine.conversations[0].closed is True
    assert isinstance(engine.conversations[1].commands[0], ProjectCommittedItem)
    assert active.resolve(context()).conversation is conversation

    await conversation.send(
        RequestResponse(
            command_id="after-reconfigure",
            idempotency_key="after-reconfigure",
            context=context(),
            response_id="response-2",
            minimum_thread_sequence=1,
        )
    )
    assert engine.conversations[1].commands[-1].response_id == "response-2"
    await conversation.close()


async def test_runtime_replay_projects_only_confirmed_delivered_speech_prefix() -> None:
    journal = InMemoryConversationJournal()
    committed = await journal.append(
        ConversationItemDraft(
            item_id="assistant-1",
            context=replace(context(), response_id="response-1"),
            kind=ConversationItemKind.ASSISTANT_OUTPUT,
            status=ConversationItemStatus.INTERRUPTED,
            producer="test",
            content=(TextContent("完整语义内容"),),
            spoken=SpokenContent("已经送达，后面没播完"),
        )
    )
    deliveries = InMemorySpeechDeliveryStore()
    await deliveries.start(
        SpeechDeliveryRecord(
            speech_id="response:response-1",
            context=replace(context(), response_id="response-1"),
            source_item_id="assistant-1",
            context_policy=SpeechContextPolicy.AUTO,
            interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
        )
    )
    await deliveries.append_text(
        "response:response-1",
        "已经送达，后面没播完",
    )
    await deliveries.commit_text("response:response-1")
    await deliveries.report_progress(
        "response:response-1",
        delivered_text_end=len("已经送达"),
        played_audio_end_us=300_000,
        precision=PlaybackPrecision.SEGMENT,
        completed=False,
    )
    await deliveries.cancel("response:response-1", reason="barge_in")
    engine = RecordingEngine()

    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=journal,
        speech_deliveries=deliveries,
        active_conversations=ActiveRealtimeConversations(),
    ).open(context=context(), profile=None)

    projected = engine.conversation.commands[0]
    assert isinstance(projected, ProjectCommittedItem)
    assert projected.item.sequence == committed.item.sequence
    assert projected.item.content == (TextContent("已经送达"),)
    await conversation.close()


async def test_reconfigure_cancels_active_response_before_closing_old_runtime() -> None:
    engine = RecordingEngine()
    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
    ).open(context=context(), profile="profile-a")
    await conversation.send(
        RequestResponse(
            command_id="response-1",
            idempotency_key="response-1",
            context=context(),
            response_id="response-1",
            minimum_thread_sequence=0,
        )
    )

    await conversation.reconfigure(profile="profile-b")

    assert isinstance(engine.conversations[0].commands[-1], CancelResponse)
    assert engine.conversations[0].commands[-1].reason == "reconfiguration"
    event = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(event, ResponseCancelled)
    assert event.conversation_sequence == 1
    await conversation.close()


async def test_failed_reconfiguration_reopens_previous_profile() -> None:
    engine = RejectingProfileEngine()
    active = ActiveRealtimeConversations()
    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=InMemoryConversationJournal(),
        active_conversations=active,
    ).open(context=context(), profile="profile-a")

    with pytest.raises(RuntimeError, match="profile-b cannot open"):
        await conversation.reconfigure(profile="profile-b")

    await conversation.send(
        RequestResponse(
            command_id="after-rollback",
            idempotency_key="after-rollback",
            context=context(),
            response_id="response-after-rollback",
            minimum_thread_sequence=0,
        )
    )
    assert engine.opened_profiles == ["profile-a", "profile-b", "profile-a"]
    assert engine.conversations[-1].commands[-1].response_id == (
        "response-after-rollback"
    )
    assert active.resolve(context()).conversation is conversation
    await conversation.close()


async def test_engine_resolver_can_migrate_between_engine_implementations() -> None:
    cascaded = RecordingEngine()
    native = RecordingEngine()
    conversation = await RealtimeRuntimeFactory(
        engine_resolver=lambda profile: native if profile == "native" else cascaded,
        journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
    ).open(context=context(), profile="cascaded")

    await conversation.reconfigure(profile="native")

    assert cascaded.conversations[0].closed is True
    assert len(native.conversations) == 1
    await conversation.close()


class StaticFailureRecovery:
    def __init__(self, replacement_profile: object) -> None:
        self.replacement_profile = replacement_profile
        self.events = []

    async def recovery_profile(self, *, current_profile, event):
        self.events.append((current_profile, event))
        return self.replacement_profile


async def test_capability_failure_automatically_reconfigures_the_managed_runtime() -> None:
    engine = RecordingEngine()
    recovery = StaticFailureRecovery("profile-b")
    conversation = await RealtimeRuntimeFactory(
        engine=engine,
        journal=InMemoryConversationJournal(),
        active_conversations=ActiveRealtimeConversations(),
        failure_recovery=recovery,
    ).open(context=context(), profile="profile-a")
    await engine.conversations[0].event_queue.put(
        RealtimeCapabilityFailed(
            event_id="asr-failed",
            context=context(),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            capability="asr",
            error="connection lost",
        )
    )

    event = await asyncio.wait_for(anext(conversation.events()), timeout=0.2)
    assert isinstance(event, RealtimeCapabilityFailed)
    await asyncio.wait_for(engine.second_opened.wait(), timeout=0.2)

    assert engine.opened_profiles == ["profile-a", "profile-b"]
    assert recovery.events[0][0] == "profile-a"
    await conversation.close()
