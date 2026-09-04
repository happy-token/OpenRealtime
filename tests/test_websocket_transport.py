from collections.abc import AsyncIterator

import pytest

from server.transport import frames
from server.transport.base import AuthenticatedTransportIdentity
from server.transport.frame_parsing import parse_inbound_frame
from server.transport.frames import (
    AvatarPersonaConfigFrame,
    AssistantTextFrame,
    ClientConnectionQualityFrame,
    ConfirmationDecisionFrame,
    PlaybackProgressFrame,
    PlaybackQualityFrame,
    TtsConfigFrame,
    UserTextFrame,
)
from server.transport.plugins.websocket import (
    StaticBearerWebSocketAuthenticator,
    WebSocketTransportAdapter,
)
from server.voice_session.protocol import (
    InputAudioFrame,
    InputCaptureDiagnostic,
    InputEpochStarted,
    VoiceSessionFailureFrame,
)


class FakeConnection:
    """Test double standing in for a websockets ServerConnection."""

    def __init__(self, incoming: list[str]) -> None:
        self._incoming = incoming
        self.sent: list[str] = []
        self.closed = False

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for message in self._incoming:
            yield message

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


async def _collect(adapter: WebSocketTransportAdapter) -> list:
    return [frame async for frame in adapter.receive()]


async def test_receive_parses_user_text_frame():
    connection = FakeConnection(['{"type": "user_text", "text": "hello"}'])
    adapter = WebSocketTransportAdapter(connection)

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="hello")]


async def test_receive_parses_avatar_persona_selection_without_prompt_content():
    connection = FakeConnection(
        ['{"type":"avatar_persona_config","avatar_id":"avatar-zhaoning"}']
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert received == [AvatarPersonaConfigFrame(avatar_id="avatar-zhaoning")]


def test_removed_v1_audio_chunk_frame_is_rejected() -> None:
    assert parse_inbound_frame(
        '{"type":"audio_chunk","pcm16_base64":"AAA=","sample_rate_hz":16000}'
    ) is None


async def test_receive_parses_v2_input_epoch_and_audio_frame() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"input_epoch_started","input_epoch":"input-1",'
                '"format":{"format_id":"pcm16-16k-mono"},'
                '"requested_profile":{},"effective_profile":{}}'
            ),
            (
                '{"type":"input_audio_frame","input_epoch":"input-1","sequence":0,'
                '"start_sample":0,"sample_count":512,"capture_mode":"live",'
                '"pcm16_base64":"AAA="}'
            ),
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert isinstance(received[0], InputEpochStarted)
    assert isinstance(received[1], InputAudioFrame)


async def test_receive_parses_content_free_input_capture_diagnostic() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"input_capture_diagnostic","input_epoch":"input-1",'
                '"outcome":"overflow","buffered_frames":938,'
                '"buffered_duration_ms":30016,"aggregate_energy":0.12}'
            )
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert received == [
        InputCaptureDiagnostic(
            input_epoch="input-1",
            outcome="overflow",
            buffered_frames=938,
            buffered_duration_ms=30016,
            aggregate_energy=0.12,
        )
    ]


async def test_receive_rejects_raw_audio_in_input_capture_diagnostic() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"input_capture_diagnostic","input_epoch":"input-1",'
                '"outcome":"overflow","pcm16_base64":"AAAA"}'
            )
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    assert await _collect(adapter) == []


async def test_receive_parses_client_playback_start_and_stop_diagnostics() -> None:
    connection = FakeConnection(
        [
            '{"type":"playback_progress","generation":3,"finished":false,"started":true}',
            '{"type":"playback_progress","generation":3,"finished":false,"stopped":true}',
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert len(received) == 2
    assert isinstance(received[0], PlaybackProgressFrame)
    assert received[0].started is True
    assert received[0].stopped is False
    assert isinstance(received[1], PlaybackProgressFrame)
    assert received[1].started is False
    assert received[1].stopped is True


async def test_receive_parses_aggregated_playback_quality_without_media_content() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"playback_quality","generation":4,"arrival_jitter_ms":18.5,'
                '"max_chunk_gap_ms":92.0,"underrun_count":2,"underrun_total_ms":44.0,'
                '"chunk_count":23}'
            )
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert received == [
        PlaybackQualityFrame(
            generation=4,
            arrival_jitter_ms=18.5,
            max_chunk_gap_ms=92.0,
            underrun_count=2,
            underrun_total_ms=44.0,
            chunk_count=23,
        )
    ]


async def test_receive_parses_client_connection_quality() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"client_connection_quality","reconnect_count":2,'
                '"last_disconnect_ms":860.5,"max_disconnect_ms":1420.0}'
            )
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert received == [
        ClientConnectionQualityFrame(
            reconnect_count=2,
            last_disconnect_ms=860.5,
            max_disconnect_ms=1420.0,
        )
    ]


async def test_receive_parses_tts_session_config() -> None:
    connection = FakeConnection(
        ['{"type":"tts_config","provider":"bailian","voice":"longanhuan_v3","speech_rate":20,"dialect":"cantonese"}']
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert received == [
        TtsConfigFrame(
            provider="bailian",
            voice="longanhuan_v3",
            speech_rate=20,
            dialect="cantonese",
        )
    ]


async def test_receive_drops_malformed_json():
    connection = FakeConnection(["not json", '{"type": "user_text", "text": "ok"}'])
    adapter = WebSocketTransportAdapter(connection)

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="ok")]


async def test_receive_drops_unknown_frame_type():
    connection = FakeConnection(['{"type": "bogus"}', '{"type": "user_text", "text": "ok"}'])
    adapter = WebSocketTransportAdapter(connection)

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="ok")]


async def test_v2_receive_rejects_invalid_command_with_structured_failure() -> None:
    connection = FakeConnection(
        [
            '{"type":"session_hello","supported_protocol_versions":[2]}',
            '{"type":"bogus"}',
        ]
    )
    adapter = WebSocketTransportAdapter(connection)

    received = await _collect(adapter)

    assert len(received) == 1
    failure = VoiceSessionFailureFrame.model_validate_json(connection.sent[0])
    assert failure.code == "invalid_command"
    assert failure.phase == "starting"
    assert failure.retryable is False
    assert failure.session_disposition == "close"
    assert connection.closed is True


async def test_receive_drops_frame_missing_required_field():
    connection = FakeConnection(['{"type": "audio_chunk"}', '{"type": "user_text", "text": "ok"}'])
    adapter = WebSocketTransportAdapter(connection)

    frames = await _collect(adapter)

    assert frames == [UserTextFrame(text="ok")]


async def test_send_serializes_assistant_text_frame_as_json():
    connection = FakeConnection([])
    adapter = WebSocketTransportAdapter(connection)

    await adapter.send(AssistantTextFrame(text="hi there", generation=3))

    assert connection.sent == [
        '{"type":"assistant_text","text":"hi there","generation":3,"emotion":null,"gesture":null}'
    ]


async def test_close_closes_the_underlying_connection():
    connection = FakeConnection([])
    adapter = WebSocketTransportAdapter(connection)

    await adapter.close()

    assert connection.closed


def test_transport_exposes_session_speech_capabilities_frame() -> None:
    frame_type = getattr(frames, "SessionCapabilitiesFrame", None)

    assert frame_type is not None
    frame = frame_type(
        server_asr=False,
        server_tts=False,
        assistant_text_streaming=True,
        user_transcript_streaming=False,
    )
    assert frame.model_dump() == {
        "type": "session_capabilities",
        "server_asr": False,
        "server_tts": False,
        "assistant_text_streaming": True,
        "user_transcript_streaming": False,
        "tts_configurable": False,
        "tts_preview": False,
        "protocol_version": 1,
        "heartbeat_interval_ms": None,
    }


def test_static_bearer_authenticator_accepts_header_or_secure_cookie() -> None:
    identity = AuthenticatedTransportIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="browser-1",
    )
    authenticator = StaticBearerWebSocketAuthenticator(
        token="a-secure-static-bearer-token-0001",
        identity=identity,
    )

    assert (
        authenticator.authenticate(
            {"Authorization": "Bearer a-secure-static-bearer-token-0001"}
        )
        == identity
    )
    assert (
        authenticator.authenticate(
            {
                "Cookie": (
                    "other=value; "
                    "openrealtime_endpoint_token=a-secure-static-bearer-token-0001"
                )
            }
        )
        == identity
    )
    assert authenticator.authenticate({"Authorization": "Bearer wrong"}) is None
    assert authenticator.authenticate({"Cookie": "bad-cookie=\""}) is None
    assert authenticator.authenticate({}) is None

    with pytest.raises(ValueError, match="at least 32"):
        StaticBearerWebSocketAuthenticator(token="weak", identity=identity)


def test_transport_exposes_response_completed_frame() -> None:
    frame_type = getattr(frames, "AssistantResponseCompletedFrame", None)

    assert frame_type is not None


def test_confirmation_decision_frame_requires_bound_identity() -> None:
    parsed = parse_inbound_frame(
        '{"type":"confirmation_decision","confirmation_id":"confirmation-1",'
        '"action_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"approved":true}'
    )

    assert isinstance(parsed, ConfirmationDecisionFrame)
    assert parsed.confirmation_id == "confirmation-1"
    assert parse_inbound_frame(
        '{"type":"confirmation_decision","confirmation_id":"confirmation-1",'
        '"action_digest":"wrong","approved":true}'
    ) is None
