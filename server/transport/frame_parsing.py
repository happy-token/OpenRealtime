"""Shared inbound-frame JSON parsing, reused by every wire-level Transport
Adapter (WebSocket, UDP) so frame-type dispatch and malformed-frame
handling live in one place. See CONTEXT.md — Transport Adapter.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from server.transport.frames import (
    AvatarPersonaConfigFrame,
    ToolConfigFrame,
    CancelAssistantResponseFrame,
    ClientConnectionQualityFrame,
    ConfirmationDecisionFrame,
    InboundFrame,
    PlaybackProgressFrame,
    PlaybackQualityFrame,
    SessionHeartbeatFrame,
    SessionHelloFrame,
    TtsConfigFrame,
    UserTextFrame,
)
from server.voice_session.protocol import (
    InputAudioFrame,
    InputCaptureDiagnostic,
    InputEpochStarted,
    PlaybackProgressV2,
)

logger = logging.getLogger(__name__)


def parse_inbound_frame(raw_message: str | bytes) -> InboundFrame | None:
    try:
        payload = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Dropping non-JSON frame from transport")
        return None

    frame_type = payload.get("type")
    try:
        if frame_type == "input_epoch_started":
            return InputEpochStarted.model_validate(payload)
        if frame_type == "input_audio_frame":
            return InputAudioFrame.model_validate(payload)
        if frame_type == "input_capture_diagnostic":
            return InputCaptureDiagnostic.model_validate(payload)
        if frame_type == "user_text":
            return UserTextFrame.model_validate(payload)
        if frame_type == "cancel_assistant_response":
            return CancelAssistantResponseFrame.model_validate(payload)
        if frame_type == "session_hello":
            return SessionHelloFrame.model_validate(payload)
        if frame_type == "session_heartbeat":
            return SessionHeartbeatFrame.model_validate(payload)
        if frame_type == "playback_progress":
            return PlaybackProgressFrame.model_validate(payload)
        if frame_type == "playback_progress_v2":
            return PlaybackProgressV2.model_validate(payload)
        if frame_type == "playback_quality":
            return PlaybackQualityFrame.model_validate(payload)
        if frame_type == "client_connection_quality":
            return ClientConnectionQualityFrame.model_validate(payload)
        if frame_type == "tts_config":
            return TtsConfigFrame.model_validate(payload)
        if frame_type == "avatar_persona_config":
            return AvatarPersonaConfigFrame.model_validate(payload)
        if frame_type == "tool_config":
            return ToolConfigFrame.model_validate(payload)
        if frame_type == "confirmation_decision":
            return ConfirmationDecisionFrame.model_validate(payload)
    except ValidationError:
        logger.warning("Dropping malformed %s frame", frame_type)
        return None

    logger.warning("Dropping unknown frame type: %r", frame_type)
    return None
