"""Minimal GPT Voice-style coordinator reference implementation."""

from server.gpt_voice_reference.coordinator import OpenRealtime
from server.gpt_voice_reference.in_memory import (
    InMemoryRealtimeSession,
    InMemoryToolExecutor,
    InMemoryWorkerManager,
)

# Backward-compatible import for callers created before the OpenRealtime rebrand.
VoiceAgent = OpenRealtime
from server.gpt_voice_reference.models import (
    CallTool,
    DelegateTask,
    EndSession,
    RequireConfirmation,
    Speak,
)

__all__ = [
    "CallTool",
    "DelegateTask",
    "EndSession",
    "InMemoryRealtimeSession",
    "InMemoryToolExecutor",
    "InMemoryWorkerManager",
    "OpenRealtime",
    "RequireConfirmation",
    "Speak",
    "VoiceAgent",
]
