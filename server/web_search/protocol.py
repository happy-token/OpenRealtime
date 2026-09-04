"""Web Search: contract for retrieving passages relevant to a query from an
external, real-time source, as distinct from the project's own Knowledge
Base (which grounds answers in registered/static documents).

See CONTEXT.md — WebSearch, and ADR-0014. This Protocol is retrieval-only
and knows nothing about tool-calling machinery — server.tools.
web_search_source adapts it into a CanonicalTool separately, mirroring how
knowledge_base/protocol.py stays independent of the Tool Normalization
layer (ADR-0010).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

LookupFailureReason = Literal[
    "provider_unavailable",
    "timeout",
    "http_error",
    "invalid_response",
    "empty_result",
    "pipeline_timeout",
]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One normalized result. Provider payloads never cross this boundary."""

    title: str
    url: str
    summary: str
    source: str = ""
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class LookupEvidence:
    """Structured, explicitly untrusted evidence returned by a provider."""

    provider: str
    query: str
    results: tuple[SearchResult, ...]
    retrieved_at: str

    def structured(self) -> dict[str, object]:
        return {
            "untrusted": True,
            "provider": self.provider,
            "query": self.query,
            "retrieved_at": self.retrieved_at,
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "summary": result.summary,
                    "source": result.source,
                    "published_at": result.published_at,
                }
                for result in self.results
            ],
        }

    def model_text(self, *, max_characters: int = 12_000) -> str:
        blocks: list[str] = []
        for index, result in enumerate(self.results, start=1):
            metadata = [
                value
                for value in (
                    f"source={result.source}" if result.source else "",
                    f"published_at={result.published_at}" if result.published_at else "",
                    f"retrieved_at={self.retrieved_at}",
                )
                if value
            ]
            blocks.append(
                "\n".join(
                    value
                    for value in (
                        f"{index}. {result.title}",
                        result.summary,
                        result.url,
                        f"({', '.join(metadata)})" if metadata else "",
                    )
                    if value
                )
            )
        return "\n\n".join(blocks)[:max_characters]

    def public_sources(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "title": result.title,
                "url": result.url,
                "source": result.source,
            }
            for result in self.results
            if result.url
        )


class LookupFailure(RuntimeError):
    """Stable failure vocabulary shared by every search provider."""

    def __init__(
        self,
        reason: LookupFailureReason,
        *,
        provider: str,
        detail: str = "",
    ) -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.provider = provider
        self.detail = detail


class WebSearch(Protocol):
    async def search(self, query: str, *, top_k: int = 3) -> LookupEvidence: ...
