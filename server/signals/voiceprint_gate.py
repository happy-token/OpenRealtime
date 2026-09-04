"""VoiceprintGate: an opt-in HookPoint middleware that vetoes turns whose
buffered audio doesn't match the enrolled voiceprint, and lets a host
application manually confirm and resubmit a vetoed turn.

See CONTEXT.md — Voiceprint, and ADR-0005/ADR-0023. Not constructed or
referenced by the Voice Session runtime or any example by default — ADR-0005's
"voiceprint metadata never gates a turn policy transition by default"
guarantee holds exactly as before unless a host application explicitly
registers this as its own before_turn_policy_hook (see ADR-0002).
"""

from __future__ import annotations

import time

from server.voiceprint.matching import EnrolledSpeakerVoiceprintMatcher

DEFAULT_TTL_S = 30.0


class VoiceprintGate:
    """A HookPoint-compatible Middleware (see hooks/hook_point.py — a sync
    `__call__(value: str) -> str | None`, no `await`, no `generation`
    parameter). Reads EnrolledSpeakerVoiceprintMatcher.last_result
    synchronously rather than awaiting `match()` itself — see
    voiceprint/matching.py's module docstring for why `add_audio` eagerly
    computes and caches that result ahead of the hook firing.

    Vetoes (returns None) only on a confirmed `"no_match"`; `"unavailable"`
    and `"adaptive"` pass the text through unchanged, since neither is a
    positive signal of a mismatch. A vetoed turn's text is stored keyed by
    generation, with a TTL, so a host's own control-message handler can call
    `confirm(generation)` to retrieve it and resubmit it (e.g. as a fresh
    UserTextFrame) once a human confirms it really was them."""

    def __init__(
        self,
        matcher: EnrolledSpeakerVoiceprintMatcher,
        *,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> None:
        self._matcher = matcher
        self._ttl_s = ttl_s
        self._pending: dict[int, tuple[str, float]] = {}

    def __call__(self, value: str) -> str | None:
        last_result = self._matcher.last_result
        if last_result is None or last_result[1] != "no_match":
            return value

        generation, _result = last_result
        self._pending[generation] = (value, time.monotonic() + self._ttl_s)
        return None

    def confirm(self, generation: int) -> str | None:
        """Retrieve and clear a vetoed turn's text, if one is pending for
        `generation` and its TTL hasn't elapsed. Returns None otherwise —
        including once a confirmation has already been consumed."""
        entry = self._pending.pop(generation, None)
        if entry is None:
            return None
        text, expires_at = entry
        if time.monotonic() > expires_at:
            return None
        return text
