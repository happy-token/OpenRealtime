"""Adapts skill declarations (name + free-text description, no formal
parameter schema) into the Canonical Tool Schema.

See CONTEXT.md — Canonical Tool Schema, and ADR-0001.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from server.tools.canonical import CanonicalTool, ToolHandler


@dataclass(frozen=True)
class SkillDeclaration:
    name: str
    description: str
    handler: ToolHandler


class SkillToolSource:
    def __init__(self, declarations: Sequence[SkillDeclaration]) -> None:
        self._declarations = list(declarations)

    def list_tools(self) -> list[CanonicalTool]:
        return [
            CanonicalTool(
                name=declaration.name,
                description=declaration.description,
                parameters={},
                handler=declaration.handler,
            )
            for declaration in self._declarations
        ]
