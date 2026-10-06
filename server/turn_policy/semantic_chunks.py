"""Revision-aware independent semantic chunks, without provider or turn side effects."""

from __future__ import annotations

import heapq
import re
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from itertools import islice

_BOUNDARIES = frozenset("，,；;。？！?!\n")
_UNITS = re.compile(r"[\u3400-\u9fff]|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?|[^\s\w]", re.UNICODE)


def _boundary_candidates(text: str) -> Iterator[tuple[int, int]]:
    """Yield (earliest suffix start, position) without scanning any prefix twice."""
    scheme_start = -1
    for index, character in enumerate(text):
        if character.isspace():
            scheme_start = -1
        if character == "/" and index >= 2 and text[index - 2 : index + 1] == "://":
            scheme_start = index - 2
        if character in _BOUNDARIES:
            yield 0, index
        elif character == ".":
            if (
                index > 0
                and index + 1 < len(text)
                and text[index - 1].isalnum()
                and text[index + 1].isalnum()
            ):
                # A decimal/domain dot becomes punctuation only if a cut starts at it.
                yield index, index
            else:
                # A cut after the colon removes the complete :// from this word.
                yield scheme_start + 1 if scheme_start >= 0 else 0, index


class _BoundaryIndex:
    """Monotone suffix queries preserve URL/decimal rules with bounded total work."""

    def __init__(self, text: str) -> None:
        self._pending = list(_boundary_candidates(text))
        heapq.heapify(self._pending)
        self._eligible: list[int] = []

    def next(self, cursor: int) -> int | None:
        while self._pending and self._pending[0][0] <= cursor:
            _, position = heapq.heappop(self._pending)
            heapq.heappush(self._eligible, position)
        while self._eligible and self._eligible[0] < cursor:
            heapq.heappop(self._eligible)
        return self._eligible[0] + 1 if self._eligible else None


def semantic_text(text: str) -> str:
    return "".join(
        c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


@dataclass(frozen=True, slots=True)
class SemanticChunk:
    """A buffer-owned candidate; semantic_end counts non-space, non-punctuation characters."""

    chunk_id: str
    text: str
    revision: int
    semantic_end: int
    trigger: str
    sequence: int
    issued: bool = False
    feedback: bool | None = None


class SemanticChunkBuffer:
    def __init__(self, *, character_limit: int = 64) -> None:
        if (
            isinstance(character_limit, bool)
            or not isinstance(character_limit, int)
            or character_limit < 1
        ):
            raise ValueError("chunk character limit must be positive")
        self.character_limit = character_limit
        self._chunks: list[SemanticChunk] = []
        self._chunk_ends: dict[str, int] = {}
        self._text = ""
        self._semantic = ""
        self._sequence = 0

    @property
    def history_size(self) -> int:
        return len(self._chunks)

    def valid(self, chunk: SemanticChunk) -> bool:
        return self._chunk_ends.get(chunk.chunk_id) == chunk.semantic_end

    def cumulative_text(self, chunk: SemanticChunk) -> str | None:
        if not self.valid(chunk):
            return None
        if len(self._semantic) == chunk.semantic_end:
            return self._text
        count = 0
        for index, character in enumerate(self._text):
            count += len(semantic_text(character))
            if count == chunk.semantic_end:
                end = index + 1
                # Keep separators belonging to this boundary, but no subsequent semantics.
                while end < len(self._text) and not semantic_text(self._text[end]):
                    end += 1
                return self._text[:end]
        return None

    def mark_issued(self, chunk: SemanticChunk) -> None:
        # Keep issue evidence with the revision record, rather than duplicate full history.
        for index, recorded in enumerate(self._chunks):
            if recorded.chunk_id == chunk.chunk_id:
                self._chunks[index] = replace(recorded, issued=True)
                return

    def context_before(self, chunk: SemanticChunk) -> tuple[str, ...]:
        preceding = []
        for recorded in reversed(self._chunks):
            if recorded.sequence < chunk.sequence and recorded.issued:
                preceding.append(recorded.text)
                if len(preceding) == 2:
                    break
        return tuple(reversed(preceding))

    def record_feedback(self, chunk: SemanticChunk, feedback: bool) -> None:
        for index, recorded in enumerate(self._chunks):
            if recorded.chunk_id == chunk.chunk_id:
                self._chunks[index] = replace(recorded, feedback=feedback)
                return

    def feedback_only_before(self, chunk: SemanticChunk) -> bool:
        if not self.valid(chunk):
            return False
        # A tail result describes the whole prefix only when every predecessor is proven feedback.
        # Unknown and unissued predecessors cannot be treated as an affirmative result.
        return all(
            recorded.feedback is True
            for recorded in self._chunks
            if recorded.sequence < chunk.sequence
        )

    def merge_pending(self, chunks: list[SemanticChunk]) -> SemanticChunk:
        merged = replace(
            chunks[-1],
            chunk_id=uuid.uuid4().hex,
            text="".join(chunk.text for chunk in chunks),
            trigger="queue_merge",
        )
        identifiers = {chunk.chunk_id for chunk in chunks}
        self._chunks = [chunk for chunk in self._chunks if chunk.chunk_id not in identifiers]
        for identifier in identifiers:
            self._chunk_ends.pop(identifier, None)
        self._chunks.append(merged)
        self._chunk_ends[merged.chunk_id] = merged.semantic_end
        return merged

    @property
    def pending_boundary(self) -> str | None:
        consumed = self._chunks[-1].semantic_end if self._chunks else 0
        count = 0
        boundaries = {
            position for activation, position in _boundary_candidates(self._text) if activation == 0
        }
        for index, character in enumerate(self._text):
            count += len(semantic_text(character))
            if count > consumed and index in boundaries:
                return semantic_text(self._text[: index + 1])
        return None

    def update(
        self, text: str, *, revision: int, stable: bool = False, force: bool = False
    ) -> tuple[SemanticChunk, ...]:
        clean = semantic_text(text)
        common = 0
        for previous, current in zip(self._semantic, clean):
            if previous != current:
                break
            common += 1
        # A candidate keeps its identity only while its entire semantic range survives.
        # Once removed, its ID cannot revive when a later ASR revision restores old text.
        self._chunks = [chunk for chunk in self._chunks if chunk.semantic_end <= common]
        self._chunk_ends = {chunk.chunk_id: chunk.semantic_end for chunk in self._chunks}
        self._text = text
        self._semantic = clean
        consumed = self._chunks[-1].semantic_end if self._chunks else 0
        # Map the stable semantic prefix back to the revised raw transcript.
        cursor = 0
        count = 0
        while cursor < len(text) and count < consumed:
            count += len(semantic_text(text[cursor]))
            cursor += 1
        while cursor < len(text) and not semantic_text(text[cursor]):
            cursor += 1
        emitted = []
        boundaries = _BoundaryIndex(text)
        while cursor < len(text):
            boundary = boundaries.next(cursor)
            if boundary is not None and (stable or force):
                end, trigger = boundary, "punctuation"
            elif boundary is not None and not force:
                break  # Tentative punctuation waits for the stability callback.
            else:
                units = list(
                    islice(
                        (
                            match
                            for match in _UNITS.finditer(text, cursor)
                            if semantic_text(match.group())
                        ),
                        65 if force else self.character_limit,
                    )
                )
                if force:
                    if len(units) > 64:
                        end, trigger = units[63].end(), "upper_bound"
                    else:
                        end, trigger = len(text), "speech_stop"
                elif len(units) >= self.character_limit:
                    end, trigger = units[self.character_limit - 1].end(), "character_threshold"
                else:
                    break
            chunk_text = text[cursor:end]
            cursor = end
            chunk_semantic = semantic_text(chunk_text)
            if not chunk_semantic:
                continue
            consumed += len(chunk_semantic)
            self._sequence += 1
            chunk = SemanticChunk(
                uuid.uuid4().hex,
                chunk_text,
                revision,
                consumed,
                trigger,
                self._sequence,
            )
            self._chunks.append(chunk)
            self._chunk_ends[chunk.chunk_id] = chunk.semantic_end
            emitted.append(chunk)
        return tuple(emitted)
