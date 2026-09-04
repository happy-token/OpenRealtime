import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.endpoint_session.registry import EndpointSessionRegistry
from server.transport.base import AuthenticatedTransportIdentity, TransportDisconnected
from server.transport.frames import (
    AssistantTextFrame,
    InboundFrame,
    OutboundFrame,
    SessionAckFrame,
    SessionHelloFrame,
    UserTextFrame,
)
from server.voice_session.protocol import VoiceSessionFailureFrame


class FakeTransport:
    def __init__(
        self,
        frames: list[InboundFrame],
        *,
        settle: Callable[[], Awaitable[None]] | None = None,
        authenticated_identity: AuthenticatedTransportIdentity | None = None,
    ) -> None:
        self._frames = frames
        self._settle = settle
        self.authenticated_identity = authenticated_identity
        self.sent: list[OutboundFrame] = []
        self.closed = False

    async def receive(self) -> AsyncIterator[InboundFrame]:
        for frame in self._frames:
            yield frame
            if self._settle is not None:
                await self._settle()

    async def send(self, frame: OutboundFrame) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        self.closed = True


class DisconnectingTransport(FakeTransport):
    async def send(self, frame: OutboundFrame) -> None:
        raise TransportDisconnected("browser closed")


class HoldingTransport(FakeTransport):
    def __init__(
        self,
        frames: list[InboundFrame],
        *,
        authenticated_identity: AuthenticatedTransportIdentity | None = None,
    ) -> None:
        super().__init__(
            frames,
            authenticated_identity=authenticated_identity,
        )
        self.release = asyncio.Event()

    async def receive(self) -> AsyncIterator[InboundFrame]:
        for frame in self._frames:
            yield frame
        await self.release.wait()


class RecordingRuntime:
    def __init__(self, session: InMemoryEndpointSession) -> None:
        self.session = session
        self.received: list[InboundFrame] = []
        self.finished = asyncio.Event()

    async def run(self) -> None:
        async for frame in self.session.receive():
            self.received.append(frame)
        self.finished.set()


class HangingRuntime:
    def __init__(self, session: InMemoryEndpointSession) -> None:
        self.session = session
        self.cancelled = asyncio.Event()

    async def run(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


TRUSTED_IDENTITY = AuthenticatedTransportIdentity(
    tenant_id="tenant-1",
    user_id="user-1",
    device_id="browser-1",
)


def v2_registry(**kwargs) -> EndpointSessionRegistry:
    return EndpointSessionRegistry(
        supported_protocol_versions=(2,),
        development_identity=TRUSTED_IDENTITY,
        **kwargs,
    )


async def test_fresh_connection_gets_new_session_and_ack() -> None:
    registry = EndpointSessionRegistry()
    sessions: list[InMemoryEndpointSession] = []
    runtimes: list[RecordingRuntime] = []
    transport = FakeTransport([SessionHelloFrame(), UserTextFrame(text="hi")])

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        runtime = RecordingRuntime(session)
        runtimes.append(runtime)
        return runtime

    await registry.handle_connection(transport, build_runtime)
    await asyncio.sleep(0)

    ack = transport.sent[0]
    assert isinstance(ack, SessionAckFrame)
    assert ack.resumed is False
    assert ack.session_id == sessions[0].session_id
    assert runtimes[0].received == [UserTextFrame(text="hi")]


async def test_endpoint_negotiates_one_explicit_v2_protocol_version() -> None:
    registry = v2_registry()
    transport = FakeTransport(
        [SessionHelloFrame(supported_protocol_versions=(3, 2))]
    )

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    ack = transport.sent[0]
    assert isinstance(ack, SessionAckFrame)
    assert ack.protocol_version == 2


async def test_endpoint_rejects_incompatible_protocol_without_starting_a_session() -> None:
    registry = v2_registry()
    transport = FakeTransport(
        [SessionHelloFrame(supported_protocol_versions=(1,))]
    )
    built = False

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        nonlocal built
        built = True
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    failure = transport.sent[0]
    assert isinstance(failure, VoiceSessionFailureFrame)
    assert failure.code == "protocol_incompatible"
    assert failure.retryable is False
    assert failure.session_disposition == "close"
    assert transport.closed is True
    assert built is False


async def test_v2_resume_requires_and_rotates_a_single_use_token() -> None:
    registry = v2_registry()
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    first_transport = FakeTransport(
        [SessionHelloFrame(supported_protocol_versions=(2,))]
    )
    await registry.handle_connection(first_transport, build_runtime)
    first_ack = first_transport.sent[0]
    assert isinstance(first_ack, SessionAckFrame)
    assert first_ack.resume_token is not None

    second_transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                resume_session_id=first_ack.session_id,
                resume_token=first_ack.resume_token,
            )
        ]
    )
    await registry.handle_connection(second_transport, build_runtime)
    second_ack = second_transport.sent[-1]
    assert isinstance(second_ack, SessionAckFrame)
    assert second_ack.resumed is True
    assert second_ack.resume_token is not None
    assert second_ack.resume_token != first_ack.resume_token

    replay_transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                resume_session_id=first_ack.session_id,
                resume_token=first_ack.resume_token,
            )
        ]
    )
    await registry.handle_connection(replay_transport, build_runtime)
    assert isinstance(replay_transport.sent[0], VoiceSessionFailureFrame)
    assert replay_transport.sent[0].code == "resume_rejected"


async def test_v2_resume_cannot_replace_an_active_attachment() -> None:
    registry = EndpointSessionRegistry(supported_protocol_versions=(2,))
    first_transport = HoldingTransport(
        [SessionHelloFrame(supported_protocol_versions=(2,))],
        authenticated_identity=TRUSTED_IDENTITY,
    )
    first_connection = asyncio.create_task(
        registry.handle_connection(first_transport, RecordingRuntime)
    )
    for _ in range(1000):
        if first_transport.sent:
            break
        await asyncio.sleep(0)
    first_ack = first_transport.sent[0]
    assert isinstance(first_ack, SessionAckFrame)
    assert first_ack.resume_token is not None

    competing_transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                resume_session_id=first_ack.session_id,
                resume_token=first_ack.resume_token,
            )
        ],
        authenticated_identity=TRUSTED_IDENTITY,
    )
    await registry.handle_connection(competing_transport, RecordingRuntime)

    assert isinstance(competing_transport.sent[0], VoiceSessionFailureFrame)
    assert competing_transport.sent[0].code == "resume_rejected"
    assert competing_transport.closed is True

    first_transport.release.set()
    await asyncio.wait_for(first_connection, timeout=1.0)


async def test_v2_resume_token_is_bound_to_trusted_transport_identity() -> None:
    registry = EndpointSessionRegistry(supported_protocol_versions=(2,))

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        return RecordingRuntime(session)

    first_transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                tenant_id="forged-tenant",
                user_id="forged-user",
                device_id="forged-device",
            )
        ],
        authenticated_identity=TRUSTED_IDENTITY,
    )
    await registry.handle_connection(first_transport, build_runtime)
    first_ack = first_transport.sent[0]
    assert isinstance(first_ack, SessionAckFrame)
    assert first_ack.resume_token is not None

    attacker = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                resume_session_id=first_ack.session_id,
                resume_token=first_ack.resume_token,
                tenant_id="tenant-1",
                user_id="user-1",
                device_id="browser-1",
            )
        ],
        authenticated_identity=AuthenticatedTransportIdentity(
            tenant_id="tenant-1",
            user_id="attacker",
            device_id="browser-1",
        ),
    )
    await registry.handle_connection(attacker, build_runtime)

    assert isinstance(attacker.sent[0], VoiceSessionFailureFrame)
    assert attacker.sent[0].code == "resume_rejected"


async def test_v2_rejects_missing_trusted_transport_identity() -> None:
    registry = EndpointSessionRegistry(supported_protocol_versions=(2,))
    transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                tenant_id="self-asserted-tenant",
                user_id="self-asserted-user",
                device_id="self-asserted-device",
            )
        ]
    )

    await registry.handle_connection(transport, RecordingRuntime)

    assert isinstance(transport.sent[0], VoiceSessionFailureFrame)
    assert transport.sent[0].code == "authentication_failed"
    assert transport.closed is True


async def test_v2_session_projects_only_trusted_identity() -> None:
    registry = EndpointSessionRegistry(supported_protocol_versions=(2,))
    sessions: list[InMemoryEndpointSession] = []
    transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                tenant_id="forged-tenant",
                user_id="forged-user",
                device_id="forged-device",
            )
        ],
        authenticated_identity=TRUSTED_IDENTITY,
    )

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    assert sessions[0].authenticated_identity == TRUSTED_IDENTITY
    assert sessions[0].authorized_thread_id == sessions[0].session_id


async def test_v2_requested_thread_requires_authoritative_access_check() -> None:
    registry = v2_registry()
    transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                requested_thread_id="thread-1",
            )
        ]
    )

    await registry.handle_connection(transport, RecordingRuntime)

    assert isinstance(transport.sent[0], VoiceSessionFailureFrame)
    assert transport.sent[0].code == "authentication_failed"
    assert transport.closed is True


async def test_v2_requested_thread_uses_authoritative_access_check() -> None:
    checked: list[tuple[AuthenticatedTransportIdentity, str]] = []

    async def authorize_thread(
        identity: AuthenticatedTransportIdentity, thread_id: str
    ) -> bool:
        checked.append((identity, thread_id))
        return thread_id == "thread-allowed"

    registry = v2_registry(thread_authorizer=authorize_thread)
    sessions: list[InMemoryEndpointSession] = []
    transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                requested_thread_id="thread-allowed",
            )
        ]
    )

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    assert checked == [(TRUSTED_IDENTITY, "thread-allowed")]
    assert sessions[0].authorized_thread_id == "thread-allowed"


async def test_v2_continuation_links_previous_session_only_after_thread_authorization() -> None:
    async def authorize_thread(
        identity: AuthenticatedTransportIdentity, thread_id: str
    ) -> bool:
        return identity == TRUSTED_IDENTITY and thread_id == "thread-previous"

    async def authorize_continuation(
        identity: AuthenticatedTransportIdentity,
        previous_voice_session_id: str,
        thread_id: str,
    ) -> bool:
        return (
            identity == TRUSTED_IDENTITY
            and previous_voice_session_id == "voice-previous"
            and thread_id == "thread-previous"
        )

    registry = v2_registry(
        thread_authorizer=authorize_thread,
        continuation_authorizer=authorize_continuation,
    )
    sessions: list[InMemoryEndpointSession] = []
    transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                previous_voice_session_id="voice-previous",
                requested_thread_id="thread-previous",
            )
        ]
    )

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    ack = transport.sent[0]
    assert isinstance(ack, SessionAckFrame)
    assert ack.resumed is False
    assert ack.previous_voice_session_id == "voice-previous"
    assert ack.thread_id == "thread-previous"
    assert sessions[0].previous_voice_session_id == "voice-previous"


async def test_unknown_resume_session_id_falls_back_to_fresh_session() -> None:
    registry = EndpointSessionRegistry()
    transport = FakeTransport([SessionHelloFrame(resume_session_id="does-not-exist")])

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    ack = transport.sent[0]
    assert isinstance(ack, SessionAckFrame)
    assert ack.resumed is False
    assert ack.session_id != "does-not-exist"


async def test_resume_within_grace_period_flushes_buffered_frames_in_order() -> None:
    registry = EndpointSessionRegistry(grace_period_s=5.0)
    transport1 = FakeTransport([SessionHelloFrame()])
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport1, build_runtime)
    session = sessions[0]

    buffered_1 = AssistantTextFrame(text="buffered-1", generation=0)
    buffered_2 = AssistantTextFrame(text="buffered-2", generation=0)
    await session.send(buffered_1)
    await session.send(buffered_2)

    transport2 = FakeTransport([SessionHelloFrame(resume_session_id=session.session_id)])
    await registry.handle_connection(transport2, build_runtime)

    ack = transport2.sent[-1]
    assert isinstance(ack, SessionAckFrame)
    assert ack.resumed is True
    assert ack.session_id == session.session_id
    assert transport2.sent[:-1] == [buffered_1, buffered_2]


async def test_grace_period_expiry_closes_and_evicts_session() -> None:
    registry = EndpointSessionRegistry(grace_period_s=0.02)
    transport = FakeTransport([SessionHelloFrame()])
    runtimes: list[RecordingRuntime] = []
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        runtime = RecordingRuntime(session)
        runtimes.append(runtime)
        return runtime

    await registry.handle_connection(transport, build_runtime)
    session_id = sessions[0].session_id

    await asyncio.wait_for(runtimes[0].finished.wait(), timeout=1.0)

    other_transport = FakeTransport([SessionHelloFrame(resume_session_id=session_id)])
    await registry.handle_connection(other_transport, build_runtime)
    ack = other_transport.sent[0]
    assert isinstance(ack, SessionAckFrame)
    assert ack.resumed is False


async def test_in_memory_endpoint_session_is_structurally_a_transport_adapter() -> None:
    # A session never ends its own receive() on detach (only on close()), so
    # runtime.run() only returns once we close the session, matching how a
    # real EndpointSession keeps one Voice Session runtime across reconnects.
    transport = FakeTransport([UserTextFrame(text="hi")])
    session = InMemoryEndpointSession("session-1", transport, transport.receive())

    runtime = RecordingRuntime(session)
    run_task = asyncio.create_task(runtime.run())

    for _ in range(1000):
        if runtime.received:
            break
        await asyncio.sleep(0)

    assert runtime.received == [UserTextFrame(text="hi")]

    await session.close()
    await asyncio.wait_for(run_task, timeout=1.0)


async def test_list_sessions_reports_tracked_session_ids() -> None:
    registry = EndpointSessionRegistry()
    transport = FakeTransport([SessionHelloFrame()])
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    listed = registry.list_sessions()
    assert [entry["session_id"] for entry in listed] == [sessions[0].session_id]
    assert listed[0]["detached"] is True  # transport's frames were exhausted


async def test_close_session_evicts_and_closes_a_detached_session() -> None:
    registry = EndpointSessionRegistry(grace_period_s=5.0)
    transport = FakeTransport([SessionHelloFrame()])
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)
    session_id = sessions[0].session_id

    found = await registry.close_session(session_id)

    assert found is True
    assert registry.list_sessions() == []
    assert await asyncio.wait_for(
        sessions[0].wait_until_detached_or_closed(), timeout=1.0
    )


async def test_process_drain_is_bounded_and_reports_stalled_session_runtime() -> None:
    registry = v2_registry()
    runtimes: list[HangingRuntime] = []
    transport = FakeTransport(
        [SessionHelloFrame(supported_protocol_versions=(2,))]
    )

    def build_runtime(session: InMemoryEndpointSession) -> HangingRuntime:
        runtime = HangingRuntime(session)
        runtimes.append(runtime)
        return runtime

    connection_task = asyncio.create_task(
        registry.handle_connection(transport, build_runtime)
    )
    for _ in range(100):
        if transport.sent and runtimes:
            break
        await asyncio.sleep(0)
    ack = transport.sent[0]
    assert isinstance(ack, SessionAckFrame)

    degraded = await registry.drain(deadline_s=0.01)

    assert degraded == (ack.session_id,)
    assert registry.list_sessions() == []
    assert runtimes[0].cancelled.is_set()
    await asyncio.wait_for(connection_task, timeout=0.1)


async def test_close_session_returns_false_for_unknown_id() -> None:
    registry = EndpointSessionRegistry()

    found = await registry.close_session("does-not-exist")

    assert found is False


async def test_outbound_buffer_overflow_drops_oldest_frame() -> None:
    transport = FakeTransport([])
    session = InMemoryEndpointSession(
        "session-1", transport, transport.receive(), buffer_capacity=2
    )

    await session.detach()

    frame_1 = AssistantTextFrame(text="one", generation=0)
    frame_2 = AssistantTextFrame(text="two", generation=0)
    frame_3 = AssistantTextFrame(text="three", generation=0)
    await session.send(frame_1)
    await session.send(frame_2)
    await session.send(frame_3)

    replacement = FakeTransport([])
    await session.attach(replacement, replacement.receive())

    assert replacement.sent == [frame_2, frame_3]


async def test_send_buffers_frame_when_attached_transport_disconnects() -> None:
    transport = DisconnectingTransport([])
    session = InMemoryEndpointSession("session-1", transport, transport.receive())
    frame = AssistantTextFrame(text="replay after reconnect", generation=1)

    await session.send(frame)

    replacement = FakeTransport([])
    await session.attach(replacement, replacement.receive())
    assert replacement.sent == [frame]


async def test_v2_resume_never_replays_detached_raw_output_frames() -> None:
    registry = v2_registry(grace_period_s=5.0)
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    first_transport = FakeTransport(
        [SessionHelloFrame(supported_protocol_versions=(2,))]
    )
    await registry.handle_connection(first_transport, build_runtime)
    first_ack = first_transport.sent[0]
    assert isinstance(first_ack, SessionAckFrame)
    assert first_ack.resume_token is not None

    stale_media = AssistantTextFrame(text="detached output", generation=1)
    await sessions[0].send(stale_media)

    resumed_transport = FakeTransport(
        [
            SessionHelloFrame(
                supported_protocol_versions=(2,),
                resume_session_id=first_ack.session_id,
                resume_token=first_ack.resume_token,
            )
        ]
    )
    await registry.handle_connection(resumed_transport, build_runtime)

    assert stale_media not in resumed_transport.sent
    assert isinstance(resumed_transport.sent[0], SessionAckFrame)
