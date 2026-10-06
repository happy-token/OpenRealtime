"""Pure bounded-concurrency chunk queue, with bounded context and revision invalidation."""

from __future__ import annotations

from dataclasses import dataclass

from server.turn_policy.semantic_chunks import SemanticChunk, SemanticChunkBuffer


@dataclass(frozen=True, slots=True)
class ChunkUpdate:
    sealed: tuple[SemanticChunk, ...]
    invalidated_active: SemanticChunk | None
    merged: SemanticChunk | None
    merged_sources: tuple[str, ...]
    stability_changed: bool
    invalidated_candidates: tuple[SemanticChunk, ...] = ()


class SemanticChunkScheduler:
    def __init__(self, *, character_limit: int, pending_limit: int = 4, max_concurrency: int = 1) -> None:
        if (
            isinstance(pending_limit, bool)
            or not isinstance(pending_limit, int)
            or pending_limit < 1
        ):
            raise ValueError("pending chunk limit must be a positive integer")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ValueError("chunk concurrency must be a positive integer")
        self._max_concurrency = max_concurrency
        self._inflight: dict[str, SemanticChunk] = {}
        self._buffer = SemanticChunkBuffer(character_limit=character_limit)
        self._pending_limit = pending_limit
        self._pending: list[SemanticChunk] = []
        self._accepted: list[SemanticChunk] = []
        self._feedback_only = True
        self._stability_prefix: str | None = None

    @property
    def busy(self) -> bool:
        return bool(self._inflight) or bool(self._pending)

    @property
    def history_size(self) -> int:
        return self._buffer.history_size

    @property
    def active(self) -> SemanticChunk | None:
        return next(iter(self._inflight.values()), None)

    @property
    def previous_chunks(self) -> tuple[str, ...]:
        return tuple(chunk.text for chunk in self._accepted)

    @property
    def feedback_only(self) -> bool:
        return self._feedback_only

    @property
    def stability_prefix(self) -> str | None:
        return self._stability_prefix

    def matches_active(self, chunk_id: str) -> bool:
        chunk = self._inflight.get(chunk_id)
        return chunk is not None and self._buffer.valid(chunk)

    def context_before(self, chunk: SemanticChunk) -> tuple[str, ...]:
        return self._buffer.context_before(chunk)

    def cumulative_text(self, chunk: SemanticChunk) -> str | None:
        return self._buffer.cumulative_text(chunk)

    def feedback_only_before(self, chunk: SemanticChunk) -> bool:
        return self._buffer.feedback_only_before(chunk)

    def observe(
        self, text: str, *, revision: int, stable: bool = False, force: bool = False
    ) -> ChunkUpdate:
        sealed = self._buffer.update(text, revision=revision, stable=stable, force=force)
        retained = [chunk for chunk in self._accepted if self._buffer.valid(chunk)]
        if len(retained) != len(self._accepted):
            self._accepted = retained
            self._feedback_only = False
        self._pending = [chunk for chunk in self._pending if self._buffer.valid(chunk)]
        invalidated = None
        invalidated_candidates = []
        for chunk_id, chunk in tuple(self._inflight.items()):
            if not self._buffer.valid(chunk):
                invalidated = invalidated or chunk
                invalidated_candidates.append(chunk)
                del self._inflight[chunk_id]
                self._accepted.clear()
                self._feedback_only = False
        self._pending.extend(sealed)
        merged = None
        sources: tuple[str, ...] = ()
        if len(self._pending) > self._pending_limit:
            sources = tuple(chunk.chunk_id for chunk in self._pending)
            merged = self._buffer.merge_pending(self._pending)
            self._pending = [merged]
        prefix = self._buffer.pending_boundary
        changed = prefix != self._stability_prefix
        self._stability_prefix = prefix
        return ChunkUpdate(sealed, invalidated, merged, sources, changed, tuple(invalidated_candidates))

    def begin_next(self) -> SemanticChunk | None:
        if len(self._inflight) >= self._max_concurrency or not self._pending:
            return None
        chunk = self._pending.pop(0)
        self._inflight[chunk.chunk_id] = chunk
        self._buffer.mark_issued(chunk)
        return chunk

    def complete(self, chunk_id: str, *, feedback: bool | None = None) -> SemanticChunk | None:
        if not self.matches_active(chunk_id):
            return None
        chunk = self._inflight.pop(chunk_id)
        self._accepted = sorted([*self._accepted, chunk], key=lambda c: c.sequence)[-2:]
        if feedback is not None:
            self._buffer.record_feedback(chunk, feedback)
            self._feedback_only &= feedback
        return chunk

    def cancel_active(self) -> None:
        self._inflight.clear()
        self._pending.clear()
