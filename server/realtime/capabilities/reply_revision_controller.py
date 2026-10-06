"""Actor-owned input/reply association; no I/O, timers or semantic decisions.

Generation remains the execution lease. This ledger retains only the current
input and reply; immutable history belongs to the conversation Journal.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace

from server.conversation_journal import (
    ConversationItem,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit, sample_position_us
from server.realtime.protocol.playback import ReplyPlayback, sentence_identity
from server.realtime.scope import conversation_scope


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
    playback: ReplyPlayback | None = None
    sentence_permit: CurrentSentencePermit | None = None


class ReplyRevisionController:
    def __init__(self) -> None:
        self.input: InputRevision | None = None
        self.reply: ReplyRevision | None = None
        self._reply_context: InteractionContext | None = None
        self._sample_rate_hz: int | None = None
        self._closed = False
        self._live_started = False
        self._history_sequence = 0

    def restore_item(self, item: ConversationItem) -> bool:
        """Rebuild current identities during the Journal restoration barrier.

        Returns whether a user input was restored. No delivery permission,
        pending response or execution lease survives this barrier. Once live
        commits/bindings begin, their later Journal projections cannot roll
        back the actor's state. The caller enforces thread authorization.
        """
        if self._closed:
            raise RuntimeError("reply revision controller is closed")
        if self._live_started or item.sequence <= self._history_sequence:
            return False
        metadata = item.provider_metadata
        if item.kind is ConversationItemKind.USER_INPUT and item.status is ConversationItemStatus.COMPLETED:
            text = "\n".join(part.text for part in item.content if isinstance(part, TextContent))
            if not text.strip():
                self._history_sequence = item.sequence
                return False
            root = metadata.get("input_id")
            version = metadata.get("input_version")
            legacy = root is None and version is None
            if legacy:
                root, version = item.item_id, 1
            root = _identity(root, "input_id")
            version = _positive_integer(version, "input_version")
            observation_value = metadata.get("input_observation_id")
            observation = _identity(item.item_id if observation_value is None else observation_value, "observation_id")
            transcript = _positive_integer(metadata.get("transcript_revision", 1), "transcript_revision")
            reason_value = metadata.get("admission_reason")
            reason = _identity("journal_restore" if reason_value is None else reason_value, "admission_reason")
            parent = metadata.get("continuation_of_turn_id") if not legacy else None
            if parent is not None:
                parent = _identity(parent, "continuation_of_turn_id")
            previous = self.input
            if previous is not None and previous.input_id == root and (
                version <= previous.input_version or observation == previous.observation_id
            ):
                raise ValueError("restored input identity or version was reused")
            if version > 1 and (previous is None or previous.input_id != root
                    or previous.input_version + 1 != version or previous.turn_id != parent):
                raise ValueError("restored input continuation has no preceding version")
            if version == 1 and parent is not None:
                raise ValueError("restored first input version cannot have a continuation")
            self.input = InputRevision(
                input_id=root, observation_id=observation, input_version=version,
                turn_id=item.context.turn_id, generation=item.context.generation,
                transcript_revision=transcript, text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                admission_reason=reason, supersedes_turn_id=parent,
            )
            if self.reply is not None and self.reply.input_id != root:
                self.reply = None
            self._history_sequence = item.sequence
            return True
        if item.kind is ConversationItemKind.ASSISTANT_OUTPUT and metadata.get("reply_version") is not None:
            reply_version = _positive_integer(metadata["reply_version"], "reply_version")
            # Manual/external replies can carry a reply version without an
            # ASR input identity. They belong in history, not this input chain.
            if metadata.get("input_id") is None and metadata.get("input_version") is None:
                self._history_sequence = item.sequence
                return False
            root = _identity(metadata.get("input_id"), "input_id")
            version = _positive_integer(metadata.get("input_version"), "input_version")
            response_id = _identity(metadata.get("response_id"), "response_id")
            if item.context.response_id != response_id:
                raise ValueError("restored reply context and response identity disagree")
            if self.input is not None and self.input.input_id == root:
                if version > self.input.input_version:
                    raise ValueError("restored reply refers to a future input version")
                if version == self.input.input_version and (
                    item.context.turn_id, item.context.generation
                ) != (self.input.turn_id, self.input.generation):
                    raise ValueError("restored reply belongs to a different input context")
                predecessor = metadata.get("supersedes_response_id")
                if predecessor is not None:
                    predecessor = _identity(predecessor, "supersedes_response_id")
                if self.reply is None or reply_version > self.reply.reply_version:
                    self.reply = ReplyRevision(
                        response_id=response_id, turn_id=item.context.turn_id, generation=item.context.generation,
                        input_id=root, input_version=version, reply_version=reply_version,
                        supersedes_response_id=predecessor, delivery_permitted=False,
                        completed=True, invalidation_reason="journal_restored",
                    )
        self._history_sequence = item.sequence
        return False

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
        self._live_started = True
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
        self._live_started = True
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
        self._reply_context = context
        self._sample_rate_hz = None
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
        retained = self.reply.sentence_permit if reason == "barge_in_floor_claim" else None
        if self.reply.delivery_permitted or self.reply.sentence_permit != retained:
            self.reply = replace(self.reply, delivery_permitted=False, invalidation_reason=reason, sentence_permit=retained)
        return self.reply

    def grant_current_sentence(self, response_id: str, *, trigger_input_id: str,
                               transcript_revision: int, now_ns: int) -> CurrentSentencePermit | None:
        reply, owner = self.reply, self._reply_context
        if (not self.delivery_allowed(response_id) or reply is None or owner is None
            or reply.input_id is None or reply.input_version is None):
            return None
        fact = reply.playback
        if (fact is None or fact.terminal or fact.position_precision != "sample"
            or fact.current_sentence is None or fact.output_epoch is None
            or fact.played_position_samples is None or fact.sample_rate_hz is None):
            return None
        sentence, rate = fact.current_sentence, fact.sample_rate_hz
        age_ns = now_ns - fact.observed_at_ns
        if not 0 <= age_ns <= 250_000_000 or fact.played_audio_end_us + age_ns // 1000 >= sentence.audio_end_us:
            return None
        start = (sentence.audio_start_us * rate + 500_000) // 1_000_000
        end = (sentence.audio_end_us * rate + 500_000) // 1_000_000
        if (sample_position_us(start, rate) != sentence.audio_start_us
            or sample_position_us(end, rate) != sentence.audio_end_us
            or not start < fact.played_position_samples < end
            or fact.confirmed_text_end > sentence.text_start):
            return None
        wait_ms = (sentence.audio_end_us - fact.played_audio_end_us + 999) // 1000 + 250
        if wait_ms > 1500:
            return None
        permit = CurrentSentencePermit(permit_id=str(uuid.uuid4()), context=owner,
            input_id=reply.input_id, input_version=reply.input_version, response_id=reply.response_id,
            reply_version=reply.reply_version, output_epoch=fact.output_epoch, speech_id=fact.speech_id,
            sentence_id=sentence.sentence_id, audio_start_samples=start, audio_end_samples=end, sample_rate_hz=rate,
            trigger_input_id=trigger_input_id, trigger_transcript_revision=transcript_revision,
            issued_at_ns=now_ns, expires_at_ns=now_ns + wait_ms * 1_000_000,
            confirmed_text_end=fact.confirmed_text_end)
        self.reply = replace(reply, sentence_permit=permit)
        return permit

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit, *, now_ns: int) -> bool:
        reply = self.reply
        fact = reply.playback if reply is not None else None
        return bool(not self._closed and reply is not None and reply.sentence_permit == permit
            and now_ns < permit.expires_at_ns and fact is not None and not fact.terminal
            and fact.position_precision == "sample" and fact.output_epoch == permit.output_epoch
            and fact.speech_id == permit.speech_id and fact.sample_rate_hz == permit.sample_rate_hz
            and fact.current_sentence is not None and fact.current_sentence.sentence_id == permit.sentence_id
            and fact.played_position_samples is not None
            and permit.audio_start_samples < fact.played_position_samples < permit.audio_end_samples)

    def observe_playback(self, response_id: str) -> None:
        if not self._closed and self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, playback_started=True)

    def observe_playback_fact(self, response_id: str, context: InteractionContext, fact: ReplyPlayback) -> bool:
        """Only the actor calls this mutation; observations cannot restore permission."""
        reply, owner = self.reply, self._reply_context
        if (self._closed or reply is None or owner is None or reply.response_id != response_id
            or conversation_scope(context) != conversation_scope(owner)
            or (context.turn_id, context.generation) != (reply.turn_id, reply.generation)
            or context.response_id not in {owner.response_id, response_id}
            or fact.speech_id not in {response_id, f"response:{response_id}"}
            or self._sample_rate_hz is not None and fact.sample_rate_hz not in {None, self._sample_rate_hz}):
            return False
        previous = reply.playback
        if fact.current_sentence is not None and (previous is None or previous.current_sentence != fact.current_sentence):
            if (previous is not None and previous.current_sentence is not None
                and previous.current_sentence.sentence_id == fact.current_sentence.sentence_id):
                raise ValueError("playback sentence identity was reused with different boundaries")
            if fact.current_sentence.sentence_id != sentence_identity(
                context, fact.speech_id, fact.current_sentence.text, fact.current_sentence.text_start,
            ):
                raise ValueError("playback sentence belongs to another output")
        if previous is not None:
            if (fact.observed_at_ns < previous.observed_at_ns and not fact.terminal
                or fact.played_audio_end_us < previous.played_audio_end_us
                or previous.played_position_samples is not None and fact.played_position_samples is not None
                    and fact.played_position_samples < previous.played_position_samples
                or fact.confirmed_text_end < previous.confirmed_text_end
                or previous.output_epoch is not None and fact.output_epoch not in {None, previous.output_epoch}):
                return False
            if previous.terminal:
                if previous.position_precision == "unknown":
                    # A later projection can refine reported history, not certify
                    # an already uncertain final stop position or its PCM clock.
                    fact = replace(fact, position_precision="unknown", current_sentence=None,
                                   played_position_samples=None, sample_rate_hz=None)
                # A late in-flight progress report may refine the heard frontier,
                # but cannot change when this output first became terminal.
                fact = replace(fact, terminal=True, current_sentence=None,
                               observed_at_ns=previous.observed_at_ns)
            if fact.output_epoch is None:
                # An estimated/legacy receipt invalidates current-sentence certainty.
                # Keep the attachment identity and monotonic heard frontier separately.
                fact = replace(fact, output_epoch=previous.output_epoch, current_sentence=None)
            if fact.played_audio_end_us == previous.played_audio_end_us and not fact.terminal:
                fact = replace(fact, observed_at_ns=previous.observed_at_ns)
        if fact.sample_rate_hz is not None:
            self._sample_rate_hz = fact.sample_rate_hz
        self.reply = replace(reply, playback=fact,
            sentence_permit=None if fact.terminal else reply.sentence_permit,
            playback_started=reply.playback_started or fact.played_audio_end_us > 0)
        return self.reply != reply

    def finish(self, response_id: str) -> None:
        if self.reply is not None and self.reply.response_id == response_id:
            self.reply = replace(self.reply, completed=True)

    def close(self) -> None:
        self._closed = True
        if self.reply is not None:
            self.revoke(self.reply.response_id, reason="session_closed")


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"restored {name} must be a non-empty string")
    return value


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"restored {name} must be a positive integer")
    return value
