"""StageTracer: per-call timing/error/timeout logging for pipeline stages.

Ported from `../realtime/server/observability/tracer.py`'s `SessionTracer`/
`Span` shape (a span always logs `duration_ms` + `status` on exit and never
swallows the exception it observed) onto stdlib `logging` (no loguru
dependency here) and this project's existing `generation` id (see
`core/generation.py`, `ledger/event_ledger.py`) instead of inventing new
turn/session ids — see docs/adr/0024-stage-tracer-timing-and-error-logging.md.

Deliberately does not aggregate (no p50/p95): per-call log lines are meant to
be searched post-hoc by `session`/`generation` when troubleshooting, not
summarized in-process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from server.ledger.event_ledger import EventLedger

logger = logging.getLogger(__name__)


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Span:
    name: str
    session_id: str
    generation: int | None
    started_at: float
    ended_at: float | None = None
    status: SpanStatus = SpanStatus.OK
    error: str | None = None
    tags: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return (end - self.started_at) * 1000


_LEVEL_BY_STATUS = {
    SpanStatus.OK: logging.INFO,
    SpanStatus.TIMEOUT: logging.WARNING,
    SpanStatus.CANCELLED: logging.WARNING,
    SpanStatus.ERROR: logging.ERROR,
}


def _log_span(span: Span) -> None:
    logger.log(
        _LEVEL_BY_STATUS[span.status],
        "stage=%s session=%s generation=%s status=%s duration_ms=%.1f tags=%s error=%s",
        span.name,
        span.session_id,
        span.generation,
        span.status.value,
        span.duration_ms,
        span.tags,
        span.error,
        exc_info=span.status is SpanStatus.ERROR,
    )


class StageTracer:
    """Session-scoped span factory. See module docstring."""

    def __init__(self, session_id: str, *, ledger: EventLedger | None = None) -> None:
        self._session_id = session_id
        self._ledger = ledger

    @asynccontextmanager
    async def span(
        self, name: str, *, generation: int | None = None, **tags: Any
    ) -> AsyncIterator[Span]:
        """Wraps one async call. Always logs `duration_ms` + `status` on
        exit and re-raises whatever it caught — never swallows."""
        span = Span(
            name=name, session_id=self._session_id, generation=generation, started_at=time.monotonic()
        )
        span.tags = tags
        try:
            yield span
        except asyncio.CancelledError:
            span.status = SpanStatus.CANCELLED
            raise
        except TimeoutError as exc:
            span.status = SpanStatus.TIMEOUT
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        except Exception as exc:
            span.status = SpanStatus.ERROR
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.ended_at = time.monotonic()
            _log_span(span)
            if self._ledger is not None and span.generation is not None:
                await self._ledger.emit(
                    "stage_span",
                    generation=span.generation,
                    stage=span.name,
                    status=span.status.value,
                    duration_ms=span.duration_ms,
                    error=span.error,
                    **span.tags,
                )

    @contextmanager
    def sync_span(
        self, name: str, *, generation: int | None = None, **tags: Any
    ) -> Iterator[Span]:
        """Sync counterpart for sync call sites (e.g. HookPoint.apply).
        Log-only — no ledger emit, since `EventLedger.emit` is async and
        there is no loop-safe way to fire-and-forget it here without risking
        an orphan task."""
        span = Span(
            name=name, session_id=self._session_id, generation=generation, started_at=time.monotonic()
        )
        span.tags = tags
        try:
            yield span
        except Exception as exc:
            span.status = SpanStatus.ERROR
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.ended_at = time.monotonic()
            _log_span(span)
