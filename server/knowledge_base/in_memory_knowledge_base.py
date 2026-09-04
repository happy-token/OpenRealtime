"""Deterministic reference implementation of the Knowledge Base contract.

InMemoryKnowledgeBase is the "EchoLlmClient of Knowledge Base" — a
no-network, in-process, case-insensitive substring-match stand-in over a
fixed set of documents supplied at construction time, never a real
vector-search/RAG backend. Adapting a real vector store, MCP knowledge
server, or hosted RAG service means implementing the KnowledgeBase Protocol
against that backend; this class is deliberately not that.
"""

from __future__ import annotations

from collections.abc import Sequence


class InMemoryKnowledgeBase:
    def __init__(self, documents: Sequence[str] = ()) -> None:
        self._documents = list(documents)

    async def search(self, query: str, *, top_k: int = 3) -> list[str]:
        query_lower = query.lower()
        matches = [doc for doc in self._documents if query_lower in doc.lower()]
        return matches[:top_k]
