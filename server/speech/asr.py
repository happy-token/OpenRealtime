"""AsrEngine Protocol: streaming speech-to-text for realtime capabilities.

An ASR adapter owns provider recognition state, not dialogue state.  It may,
however, expose the provider's sentence-final observation through
``AsrSnapshot``; the semantic endpoint gate combines that observation with VAD
activity before Turn Policy commits an end-of-turn. This module ships the
Protocol plus PreloadedAsrEngine, a deterministic
stand-in with no network dependency (the "EchoLlmClient of ASR"), for
tests and demos. See speech/doubao_asr.py for a real conformer, and
CONTEXT.md — AsrEngine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AsrSnapshot:
    """One coherent view of a long-lived streaming ASR session.

    ``revision`` advances only when recognized text changes.  A provider's
    sentence-final event is represented separately because many providers
    first emit a partial text and later finalize the exact same text.
    """

    text: str
    revision: int
    sentence_end_revision: int
    supports_sentence_end: bool = False

    @property
    def is_sentence_end(self) -> bool:
        return bool(
            self.text
            and self.revision > 0
            and self.sentence_end_revision == self.revision
        )


class AsrSession(Protocol):
    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None: ...

    async def consume_transcript(self) -> str:
        """Return the text accumulated since the last call, then clear it."""
        ...

    async def peek_transcript(self) -> str:
        """Return the text accumulated since the last consume_transcript()
        call, without clearing it. Used by EotClassifier (see
        turn_policy/eot_classifier.py) to judge semantic completeness before
        EOT commits to draining the transcript."""
        ...

    async def snapshot(self) -> AsrSnapshot:
        """Return text, monotonic text revision, and provider endpoint state."""
        ...

    async def wait_for_update(
        self,
        *,
        after_revision: int,
        after_sentence_end_revision: int,
    ) -> AsrSnapshot:
        """Wait for a newer text/final event or session death."""
        ...

    async def close(self) -> None: ...

    @property
    def is_alive(self) -> bool:
        """False once the underlying transport has failed or closed out from
        under the session (e.g. a vendor TaskFailed control frame, or the
        socket dropping). The Realtime ASR capability checks this before
        reusing a multi-turn session and discards+restarts it instead of
        pushing audio into a connection that no longer exists."""
        ...


class AsrEngine(Protocol):
    async def start_session(self) -> AsrSession: ...


class _PreloadedAsrSession:
    def __init__(self, transcript: str) -> None:
        self._transcript = transcript
        self._consumed = False

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        return None

    async def consume_transcript(self) -> str:
        if self._consumed:
            return ""
        self._consumed = True
        return self._transcript

    async def peek_transcript(self) -> str:
        return "" if self._consumed else self._transcript

    async def snapshot(self) -> AsrSnapshot:
        text = "" if self._consumed else self._transcript
        return AsrSnapshot(
            text=text,
            revision=1 if text else 0,
            sentence_end_revision=0,
            supports_sentence_end=False,
        )

    async def wait_for_update(
        self,
        *,
        after_revision: int,
        after_sentence_end_revision: int,
    ) -> AsrSnapshot:
        snapshot = await self.snapshot()
        if (
            snapshot.revision > after_revision
            or snapshot.sentence_end_revision > after_sentence_end_revision
        ):
            return snapshot
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def close(self) -> None:
        return None

    @property
    def is_alive(self) -> bool:
        return True


class PreloadedAsrEngine:
    """Deterministic stand-in with no network dependency — for tests and demos.

    Ignores all pushed audio; `consume_transcript()` returns the configured
    transcript exactly once per session, then empty strings.
    """

    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    async def start_session(self) -> AsrSession:
        return _PreloadedAsrSession(self._transcript)
