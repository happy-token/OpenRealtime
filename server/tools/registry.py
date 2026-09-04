"""ToolRegistry: aggregates ToolSources into one flat, name-unique set of
CanonicalTools. See CONTEXT.md — Canonical Tool Schema, and ADR-0001.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from server.tools.canonical import CanonicalTool, ToolBinding, ToolDescriptor


class ToolSource(Protocol):
    def list_tools(self) -> list[CanonicalTool]: ...


class ToolRegistry:
    """Empty by default (`ToolRegistry()` -> no tools registered)."""

    def __init__(self, sources: Sequence[ToolSource] = ()) -> None:
        tools = [tool for source in sources for tool in source.list_tools()]
        names = [tool.name for tool in tools]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"
        self._by_name = {tool.name: tool for tool in tools}
        self._bindings = {
            (tool.name, tool.version): tool.to_binding() for tool in tools
        }

    @classmethod
    def from_bindings(cls, bindings: Sequence[ToolBinding]) -> ToolRegistry:
        registry = cls()
        names = [binding.descriptor.name for binding in bindings]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"
        registry._bindings = {
            (binding.descriptor.name, binding.descriptor.version): binding
            for binding in bindings
        }
        registry._by_name = {
            binding.descriptor.name: CanonicalTool(
                name=binding.descriptor.name,
                version=binding.descriptor.version,
                description=binding.descriptor.description,
                parameters=binding.descriptor.input_schema,
                handler=binding.executor,
                output_schema=binding.descriptor.output_schema,
                effects=binding.descriptor.effects,
                risk=binding.descriptor.risk,
                idempotency=binding.descriptor.idempotency,
                latency=binding.descriptor.latency,
                confirmation=binding.descriptor.confirmation,
                required_scopes=binding.descriptor.required_scopes,
                default_timeout_ms=binding.descriptor.default_timeout_ms,
            )
            for binding in bindings
        }
        return registry

    def as_list(self) -> list[CanonicalTool]:
        return list(self._by_name.values())

    def get(self, name: str) -> CanonicalTool | None:
        return self._by_name.get(name)

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(binding.descriptor for binding in self._bindings.values())

    def resolve_binding(self, name: str, version: str) -> ToolBinding | None:
        return self._bindings.get((name, version))
