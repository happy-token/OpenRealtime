"""Adapts MCP-style tool declarations into the Canonical Tool Schema.

See CONTEXT.md — Canonical Tool Schema, and ADR-0001.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from server.tools.canonical import CanonicalTool, ToolHandler


@dataclass(frozen=True)
class McpToolDeclaration:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


class McpToolSource:
    def __init__(self, declarations: Sequence[McpToolDeclaration]) -> None:
        self._declarations = list(declarations)

    def list_tools(self) -> list[CanonicalTool]:
        return [
            CanonicalTool(
                name=declaration.name,
                description=declaration.description,
                parameters=declaration.input_schema,
                handler=declaration.handler,
            )
            for declaration in self._declarations
        ]
