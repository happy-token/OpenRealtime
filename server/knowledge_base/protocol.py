"""Knowledge Base: contract for retrieving passages relevant to a query, to
ground a Brain's answer (PRD point 8: RAG/知识库/MCP等外部知识注入).

See CONTEXT.md — Knowledge Base, and ADR-0010. This Protocol is
retrieval-only and knows nothing about tool-calling machinery —
server.tools.knowledge_base_source adapts it into a CanonicalTool
separately, mirroring how device_fleet/protocol.py stays independent of the
Tool Normalization layer (ADR-0003).
"""

from __future__ import annotations

from typing import Protocol


class KnowledgeBase(Protocol):
    async def search(self, query: str, *, top_k: int = 3) -> list[str]: ...
