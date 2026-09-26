"""Adapts a Knowledge Base (RAG/知识库, PRD point 8) into the Canonical Tool
Schema, so any ToolCallingBrain retrieves grounding passages the same way it
calls any other tool. See CONTEXT.md — Canonical Tool Schema, and ADR-0010.
"""

from __future__ import annotations

from typing import Any

from server.knowledge_base.protocol import KnowledgeBase
from server.tools.canonical import (
    CanonicalTool,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)

_TOOL_NAME = "search_knowledge_base"
_TOOL_DESCRIPTION = "Search the registered knowledge base for passages relevant to a query."
_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


class KnowledgeBaseToolSource:
    def __init__(self, knowledge_base: KnowledgeBase, *, top_k: int = 3) -> None:
        self._knowledge_base = knowledge_base
        self._top_k = top_k

    def list_tools(self) -> list[CanonicalTool]:
        return [
            CanonicalTool(
                name=_TOOL_NAME,
                description=_TOOL_DESCRIPTION,
                parameters=_PARAMETERS,
                handler=self._search,
                effects=frozenset({ToolEffect.READ_SENSITIVE}),
                risk=RiskLevel.MEDIUM,
                idempotency=IdempotencyClass.IDEMPOTENT,
                latency=LatencyClass.FAST,
            )
        ]

    async def _search(self, arguments: dict[str, Any]) -> str:
        results = await self._knowledge_base.search(arguments["query"], top_k=self._top_k)
        if not results:
            return "No relevant passages found."
        return "\n".join(results)
