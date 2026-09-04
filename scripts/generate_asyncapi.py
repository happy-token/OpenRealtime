"""Generate docs/asyncapi.json from server/transport/frames.py.

The frame Pydantic models are the single source of truth for the wire
protocol; this script turns each into an AsyncAPI 2.6 message/schema pair
and writes the committed output at docs/asyncapi.json. Re-run after any
change to frames.py:

    uv run python scripts/generate_asyncapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from server.transport import frames

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "asyncapi.json"

# (frame class, wire "type" value) — order matches frames.py's InboundFrame /
# OutboundFrame union members.
INBOUND_FRAMES = [
    (frames.InputAudioFrame, "input_audio_frame"),
    (frames.InputEpochStarted, "input_epoch_started"),
    (frames.InputCaptureDiagnostic, "input_capture_diagnostic"),
    (frames.PlaybackProgressV2, "playback_progress_v2"),
    (frames.SessionHelloFrame, "session_hello"),
    (frames.UserTextFrame, "user_text"),
    (frames.SessionHeartbeatFrame, "session_heartbeat"),
    (frames.PlaybackProgressFrame, "playback_progress"),
    (frames.PlaybackQualityFrame, "playback_quality"),
    (frames.ClientConnectionQualityFrame, "client_connection_quality"),
    (frames.TtsConfigFrame, "tts_config"),
    (frames.ConfirmationDecisionFrame, "confirmation_decision"),
]
OUTBOUND_FRAMES = [
    (frames.AudioGap, "audio_gap"),
    (frames.SessionAckFrame, "session_ack"),
    (frames.InputAudioAck, "input_audio_ack"),
    (frames.UserTranscriptFrame, "user_transcript"),
    (frames.AssistantTextFrame, "assistant_text"),
    (frames.AssistantSpeechTextFrame, "assistant_speech_text"),
    (frames.AssistantAudioFrame, "assistant_audio"),
    (frames.AssistantAudioChunkFrame, "assistant_audio_chunk"),
    (frames.AssistantResponseCompletedFrame, "assistant_response_completed"),
    (frames.AssistantSpeechCancelledFrame, "assistant_speech_cancelled"),
    (frames.SessionPongFrame, "session_pong"),
    (frames.SessionCapabilitiesFrame, "session_capabilities"),
    (frames.TtsConfigAckFrame, "tts_config_ack"),
    (frames.VoiceSessionFailureFrame, "voice_session_failed"),
    (frames.VoiceSessionPhaseChangedFrame, "voice_session_phase_changed"),
    (frames.VoiceSessionReadyFrame, "voice_session_ready"),
    (frames.VoiceSessionSnapshotFrame, "voice_session_snapshot"),
    (frames.VoiceSessionEventTailFrame, "voice_session_event_tail"),
    (frames.ConfirmationRequestedFrame, "confirmation_requested"),
    (frames.ConfirmationResolutionFrame, "confirmation_resolution"),
]

SESSION_CHANNEL_DESCRIPTION = """
A single logical session over one Endpoint Session (see
endpoint_session/registry.py and ADR-0019). The client sends
`session_hello` first on any new physical connection, optionally with
`resume_session_id` to reattach to a session that survived a prior
disconnect within its grace period. The server always replies with
`session_ack`, carrying the `session_id` to use going forward and whether
it was resumed or freshly minted. All other frames may flow in either
direction after that handshake completes; the server may push
`assistant_text` / `assistant_audio` / `assistant_audio_chunk` frames
unprompted, mid-turn, independent of client input.
""".strip()


def _message_component(frame_cls: type, wire_type: str) -> tuple[str, dict]:
    schema = frame_cls.model_json_schema()
    component_name = frame_cls.__name__
    message = {
        "name": wire_type,
        "title": component_name,
        "payload": {"$ref": f"#/components/schemas/{component_name}"},
    }
    return component_name, {"message": message, "schema": schema}


def build_spec() -> dict:
    schemas: dict[str, dict] = {}
    messages: dict[str, dict] = {}

    publish_refs = []
    for frame_cls, wire_type in INBOUND_FRAMES:
        component_name, parts = _message_component(frame_cls, wire_type)
        schemas[component_name] = parts["schema"]
        messages[component_name] = parts["message"]
        publish_refs.append({"$ref": f"#/components/messages/{component_name}"})

    subscribe_refs = []
    for frame_cls, wire_type in OUTBOUND_FRAMES:
        component_name, parts = _message_component(frame_cls, wire_type)
        schemas[component_name] = parts["schema"]
        messages[component_name] = parts["message"]
        subscribe_refs.append({"$ref": f"#/components/messages/{component_name}"})

    return {
        "asyncapi": "2.6.0",
        "info": {
            "title": "OpenRealtime Wire Protocol",
            "version": "0.1.0",
            "description": (
                "Frame protocol spoken over the Transport Adapter Seam "
                "(server/transport/). Generated from "
                "server/transport/frames.py by "
                "scripts/generate_asyncapi.py — do not hand-edit."
            ),
        },
        "channels": {
            "session": {
                "description": SESSION_CHANNEL_DESCRIPTION,
                "publish": {
                    "summary": "Frames a client sends to the server.",
                    "message": {"oneOf": publish_refs},
                },
                "subscribe": {
                    "summary": "Frames the server sends to the client.",
                    "message": {"oneOf": subscribe_refs},
                },
            }
        },
        "components": {"messages": messages, "schemas": schemas},
    }


def main() -> None:
    spec = build_spec()
    OUTPUT_PATH.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
