"""Actor-owned input/reply association; no I/O, timers or semantic decisions.

Generation remains the execution lease. This ledger retains only the current
input and reply; immutable history belongs to the conversation Journal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from server.core.interaction_context import InteractionContext


@dataclass(frozen=True, slots=True)
class InputRevision:
    input_id: str
    observation_id: str
    input_version: int
    turn_id: str
    generation: int
    transcript_revision: int
    text_sha256: str
    admission_reason: str
    supersedes_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyRevision:
    response_id: str
    turn_id: str
    generation: int
    input_id: str | None
    input_version: int | None
    reply_version: int
    supersedes_response_id: str | None = None
    delivery_permitted: bool = True
    playback_started: bool = False
    completed: bool = False
    invalidation_reason: str | None = None


class ReplyRevisionController:
    def __init__(self) -> None:
        self.input: InputRevision | None = None
        self.reply: ReplyRevision | None = None
        self._closed = False

    def commit_input(
        self, *, input_id: str, context: InteractionContext, text: str,
        transcript_revision: int, continuation_of_turn_id: str | None,
        admission_reason: str,
    ) -> InputRevision:
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if not input_id or not text or transcript_revision < 1 or not admission_reason:
            raise ValueError("input revision requires identity, text, revision and admission reason")
        previous = self.input
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if previous is not None and previous.observation_id == input_id:
            if (previous.turn_id, previous.generation, previous.text_sha256,
                previous.transcript_revision, previous.admission_reason,
                previous.supersedes_turn_id) != (
                    context.turn_id, context.generation, digest, transcript_revision,
                    admission_reason, continuation_of_turn_id):
                raise ValueError("input observation identity was reused with different content")
            return previous
        if continuation_of_turn_id is not None and (
            previous is None or previous.turn_id != continuation_of_turn_id
        ):
            raise ValueError("input continuation has no current parent")
        parent = previous if continuation_of_turn_id is not None else None
        self.input = InputRevision(
            input_id=parent.input_id if parent is not None else input_id,
            observation_id=input_id,
            input_version=parent.input_version + 1 if parent is not None else 1,
            turn_id=context.turn_id, generation=context.generation,
            transcript_revision=transcript_revision, text_sha256=digest,
            admission_reason=admission_reason, supersedes_turn_id=continuation_of_turn_id,
        )
        if self.reply is not None:
            self.revoke(self.reply.response_id, reason="input_replaced")
        return self.input

    def bind_response(self, response_id: str, context: InteractionContext) -> ReplyRevision:
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if not response_id:
            raise ValueError("response identity must be non-empty")
        previous = self.reply
        if previous is not None and previous.response_id == response_id:
            if (previous.turn_id, previous.generation) != (context.turn_id, context.generation):
                raise ValueError("response identity was reused for another input")
            return previous  # Repeated started never restores a revoked permission.
        current = self.input
        if current is not None and (current.turn_id, current.generation) != (
            context.turn_id, context.generation
        ):
            current = None
        ancestor = (previous if current is not None and previous is not None
                    and previous.input_id == current.input_id else None)
        self.reply = ReplyRevision(
            response_id=response_id, turn_id=context.turn_id, generation=context.generation,
            input_id=current.input_id if current is not None else None,
            input_version=current.input_version if current is not None else None,
            reply_version=ancestor.reply_version + 1 if ancestor is not None else 1,
            supersedes_response_id=ancestor.response_id if ancestor is not None else None,
        )
        return self.reply

    def delivery_allowed(self, response_id: str) -> bool:
        return bool(not self._closed and self.reply is not None
                    and self.reply.response_id == response_id and self.reply.delivery_permitted)

    def revoke(self, response_id: str, *, reason: str) -> ReplyRevision | None:
        if not reason:
            raise ValueError("reply invalidation reason must be non-empty")
        if self.reply is None or self.reply.response_id != response_id:
            return None
        if self.reply.delivery_permitted:
            self.reply = replace(self.reply, delivery_permitted=False, invalidation_reason=reason)
        return self.reply

    def observe_playback(self, response_id: str) -> None:
        if not self._closed and self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, playback_started=True)

    def finish(self, response_id: str) -> None:
        if self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, completed=True)

    def close(self) -> None:
        self._closed = True
        if self.reply is not None:
            self.revoke(self.reply.response_id, reason="session_closed")
