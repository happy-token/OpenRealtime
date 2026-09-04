"""In-process ownership and rotating proof for live Voice Sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from server.voice_session.models import VoiceSessionIdentity


class ResumeRejected(Exception):
    """Uniform rejection that does not reveal whether a session exists."""


@dataclass(slots=True)
class _Entry:
    identity: VoiceSessionIdentity
    protocol_version: int
    runtime: object
    token_hash: bytes
    attached: bool = True
    detached_at: float | None = None


class ActiveVoiceSessionRegistry:
    def __init__(self, *, grace_period_s: float = 60.0) -> None:
        if grace_period_s <= 0:
            raise ValueError("Voice Session grace period must be positive")
        self._grace_period_s = grace_period_s
        self._entries: dict[str, _Entry] = {}

    def register(
        self,
        *,
        identity: VoiceSessionIdentity,
        protocol_version: int,
        runtime: object,
    ) -> str:
        if protocol_version < 1:
            raise ValueError("Voice Session protocol version must be positive")
        if identity.voice_session_id in self._entries:
            raise ValueError("Voice Session identity is already registered")
        token = self._new_token()
        self._entries[identity.voice_session_id] = _Entry(
            identity=identity,
            protocol_version=protocol_version,
            runtime=runtime,
            token_hash=self._hash_token(token),
        )
        return token

    def detach(self, voice_session_id: str) -> None:
        entry = self._entries.get(voice_session_id)
        if entry is None:
            return
        entry.attached = False
        entry.detached_at = time.monotonic()

    def resume(
        self,
        *,
        identity: VoiceSessionIdentity,
        voice_session_id: str,
        protocol_version: int,
        resume_token: str,
    ) -> tuple[object, str]:
        entry = self._entries.get(voice_session_id)
        presented_hash = self._hash_token(resume_token)
        if (
            entry is None
            or entry.attached
            or entry.detached_at is None
            or time.monotonic() - entry.detached_at > self._grace_period_s
            or entry.identity != identity
            or entry.protocol_version != protocol_version
            or not hmac.compare_digest(entry.token_hash, presented_hash)
        ):
            raise ResumeRejected("resume rejected")

        rotated_token = self._new_token()
        entry.token_hash = self._hash_token(rotated_token)
        entry.attached = True
        entry.detached_at = None
        return entry.runtime, rotated_token

    def remove(self, voice_session_id: str) -> object | None:
        entry = self._entries.pop(voice_session_id, None)
        return entry.runtime if entry is not None else None

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _hash_token(token: str) -> bytes:
        return hashlib.sha256(token.encode()).digest()
