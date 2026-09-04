"""Public values exchanged across the minimal Voice Agent seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Speak:
    text: str


@dataclass(frozen=True)
class CallTool:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class DelegateTask:
    task: str
    acknowledgement: str


@dataclass(frozen=True)
class RequireConfirmation:
    prompt: str
    confirmation_id: str


@dataclass(frozen=True)
class EndSession:
    reason: str = "completed"


RealtimeAction = Speak | CallTool | DelegateTask | RequireConfirmation | EndSession


@dataclass(frozen=True)
class ConversationItem:
    type: str
    text: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class VoiceEvent:
    type: str
    text: str | None = None
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class VoiceSnapshot:
    items: tuple[ConversationItem, ...]
    active_tool_calls: tuple[str, ...]
    active_workers: tuple[str, ...]
    pending_confirmation: str | None
    output_active: bool
    generation: int
    phase: str
