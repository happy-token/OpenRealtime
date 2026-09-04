"""VoiceprintMatcher: an optional signal source attaching speaker-match
metadata to Turn Content.

See CONTEXT.md — Voiceprint, and ADR-0005. Purely informational — the result
is attached to TurnContent.voiceprint and never gates any Turn Policy
transition or blocks a turn. This is explicitly not identity authentication:
voice conditions make false rejects common, so hard-blocking on a mismatch
would be unsafe as a default. Unregistered (default) behavior contributes no
voiceprint metadata at all.
"""

from __future__ import annotations

from typing import Protocol

from server.core.turn_content import VoiceprintResult


class VoiceprintMatcher(Protocol):
    async def match(self, *, generation: int) -> VoiceprintResult | None: ...

    async def add_audio(self, pcm16: bytes, *, sample_rate_hz: int, generation: int) -> None: ...


class NoVoiceprintMatching:
    async def match(self, *, generation: int) -> VoiceprintResult | None:
        return None

    async def add_audio(self, pcm16: bytes, *, sample_rate_hz: int, generation: int) -> None:
        return None
