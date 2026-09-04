"""Dialogue State: the five-value FSM state. See CONTEXT.md — Dialogue State."""

from __future__ import annotations

from enum import Enum


class DialogueState(Enum):
    IDLE = "idle"
    LISTEN = "listen"
    SPEAK = "speak"
    WAIT = "wait"
    DUAL = "dual"
