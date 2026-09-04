"""Deterministic reference implementation of the WebSearch contract.

DeterministicWebSearch is the "EchoLlmClient of Web Search" — a no-network,
in-process, case-insensitive substring-match stand-in over a fixed set of
query-substring -> canned-results entries supplied at construction time,
never a real search vendor backend. Adapting a real vendor (Bing/Serper/
Bocha/etc.) means implementing the WebSearch Protocol against that vendor's
API; this class is deliberately not that — a real conformer is deferred
pending credentials/vendor decision, the same treatment already given to
RTC/MQTT transports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from server.web_search.protocol import LookupEvidence, LookupFailure, SearchResult


class DeterministicWebSearch:
    def __init__(
        self,
        results_by_query: Mapping[str, Sequence[str | SearchResult]] | None = None,
    ) -> None:
        self._results_by_query = {
            query.lower(): list(results) for query, results in (results_by_query or {}).items()
        }

    async def search(self, query: str, *, top_k: int = 3) -> LookupEvidence:
        normalized_query = query.strip()[:500]
        if not normalized_query:
            raise LookupFailure("invalid_response", provider="deterministic", detail="empty query")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise LookupFailure(
                "invalid_response",
                provider="deterministic",
                detail="top_k must be a positive integer",
            )
        query_lower = normalized_query.lower()
        for known_query, results in self._results_by_query.items():
            if known_query in query_lower:
                normalized_results = tuple(
                    result
                    if isinstance(result, SearchResult)
                    else SearchResult(
                        title=f"Deterministic result {index}",
                        url="",
                        summary=result,
                        source="deterministic",
                    )
                    for index, result in enumerate(results[:top_k], start=1)
                )
                if normalized_results:
                    return LookupEvidence(
                        provider="deterministic",
                        query=normalized_query,
                        results=normalized_results,
                        retrieved_at=datetime.now(UTC).isoformat(),
                    )
                break
        raise LookupFailure("empty_result", provider="deterministic")
