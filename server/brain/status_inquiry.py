"""StatusInquiryClassifier: the plugin interface gating pull-based delegation status queries.

See CONTEXT.md — StatusInquiryClassifier, and ADR-0006/ADR-0008. When a
delegation is pending, Kernel must tell "asking about progress" apart from
"starting a new topic" — this Protocol is the swappable answer, same shape
as AddresseeClassifier/DualIntentClassifier. KeywordStatusInquiryClassifier
is a minimal shipped heuristic, not production-grade.
"""

from __future__ import annotations

from typing import Protocol

_DEFAULT_PHRASES = (
    "怎么样了",
    "好了吗",
    "还没",
    "查到了吗",
    "怎么样",
    "how's it going",
    "hows it going",
    "any update",
    "is it done",
    "are you done",
    "still working",
)


class StatusInquiryClassifier(Protocol):
    async def is_status_inquiry(self, *, text: str, generation: int) -> bool: ...


class KeywordStatusInquiryClassifier:
    def __init__(self, phrases: tuple[str, ...] = _DEFAULT_PHRASES) -> None:
        self._phrases = tuple(phrase.lower() for phrase in phrases)

    async def is_status_inquiry(self, *, text: str, generation: int) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in self._phrases)
