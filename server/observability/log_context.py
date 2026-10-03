"""Per-session log correlation: auto-attach `voice_session_id`/`generation`
to every log record emitted while a voice session's tasks are running,
without changing any individual `logger.*()` call site.

Uses `contextvars` so correlation propagates to child tasks spawned with
`asyncio.create_task` (which copy the current context), matching
`InteractionContext`'s own `voice_session_id`/`generation` fields (see
`server/core/interaction_context.py`) rather than inventing a second
identity scheme. See docs/VOICE-PLAYBACK-SYNC-AND-LOGGING-FIX-PLAN.md.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager

_voice_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "voice_session_id", default=None
)
_generation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "generation", default=None
)


class VoiceSessionLogFilter(logging.Filter):
    """Stamps `record.voice_session_id`/`record.generation` from the
    current contextvars so a log format string can include them without
    every call site passing `extra=`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.voice_session_id = _voice_session_id.get() or "-"
        record.generation = _generation.get()
        return True


@contextmanager
def bind_voice_session_log_context(
    voice_session_id: str, *, generation: int | None = None
) -> Iterator[None]:
    """Scope log correlation to one voice session for the duration of the
    `with` block (and any child task spawned inside it)."""
    session_token = _voice_session_id.set(voice_session_id)
    generation_token = _generation.set(generation)
    try:
        yield
    finally:
        _voice_session_id.reset(session_token)
        _generation.reset(generation_token)


def set_current_generation(generation: int | None) -> None:
    """Update just the generation for the current task tree — a session's
    generation advances many times after `bind_voice_session_log_context`
    has already opened, and callers should not have to re-open the whole
    scope just to bump this one field."""
    _generation.set(generation)
