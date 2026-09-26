import pytest

from server.knowledge_base.in_memory_knowledge_base import InMemoryKnowledgeBase
from server.tools.canonical import CanonicalTool, LatencyClass
from server.tools.function_calling_source import (
    FunctionCallingDeclaration,
    FunctionCallingToolSource,
)
from server.tools.knowledge_base_source import KnowledgeBaseToolSource
from server.tools.mcp_source import McpToolDeclaration, McpToolSource
from server.tools.registry import ToolRegistry
from server.tools.skill_source import SkillDeclaration, SkillToolSource
from server.tools.web_search_source import WebSearchToolSource
from server.web_search.deterministic_web_search import DeterministicWebSearch
from server.web_search.protocol import LookupFailure


async def _handler(arguments: dict) -> str:
    return "handled"


def test_canonical_tool_holds_a_handler():
    tool = CanonicalTool(name="x", description="d", parameters={}, handler=_handler)

    assert tool.name == "x"
    assert tool.handler is _handler


def test_mcp_source_maps_input_schema_to_parameters():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    source = McpToolSource(
        [McpToolDeclaration(name="search", description="d", input_schema=schema, handler=_handler)]
    )

    tools = source.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "search"
    assert tools[0].parameters == schema


def test_function_calling_source_passes_parameters_through():
    params = {"type": "object", "properties": {"city": {"type": "string"}}}
    source = FunctionCallingToolSource(
        [FunctionCallingDeclaration(name="weather", description="d", parameters=params, handler=_handler)]
    )

    tools = source.list_tools()

    assert tools[0].name == "weather"
    assert tools[0].parameters == params


def test_skill_source_normalizes_to_empty_parameters():
    source = SkillToolSource([SkillDeclaration(name="joke", description="d", handler=_handler)])

    tools = source.list_tools()

    assert tools[0].name == "joke"
    assert tools[0].parameters == {}


def test_knowledge_base_source_exposes_a_single_search_tool():
    source = KnowledgeBaseToolSource(InMemoryKnowledgeBase(["doc a", "doc b"]))

    tools = source.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "search_knowledge_base"
    assert tools[0].latency is LatencyClass.FAST
    assert tools[0].parameters == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


async def test_knowledge_base_source_handler_joins_matching_passages():
    source = KnowledgeBaseToolSource(InMemoryKnowledgeBase(["doc about cats", "doc about dogs"]))
    tool = source.list_tools()[0]

    result = await tool.handler({"query": "cats"})

    assert result == "doc about cats"


async def test_knowledge_base_source_handler_reports_no_matches():
    source = KnowledgeBaseToolSource(InMemoryKnowledgeBase(["doc about cats"]))
    tool = source.list_tools()[0]

    result = await tool.handler({"query": "birds"})

    assert result == "No relevant passages found."


def test_web_search_source_exposes_a_single_search_web_tool():
    source = WebSearchToolSource(DeterministicWebSearch({"cats": ["doc a", "doc b"]}))

    tools = source.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "search_web"
    assert tools[0].latency is LatencyClass.VARIABLE
    assert tools[0].default_timeout_ms == 8_000
    assert tools[0].parameters == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


async def test_web_search_source_handler_joins_matching_results():
    source = WebSearchToolSource(DeterministicWebSearch({"cats": ["doc about cats"]}))
    tool = source.list_tools()[0]

    result = await tool.handler({"query": "tell me about cats"})

    assert "外部不可信数据" in result
    assert "doc about cats" in result


async def test_web_search_source_handler_reports_no_results():
    source = WebSearchToolSource(DeterministicWebSearch({"cats": ["doc about cats"]}))
    tool = source.list_tools()[0]

    with pytest.raises(LookupFailure, match="empty_result"):
        await tool.handler({"query": "birds"})


def test_registry_aggregates_sources_and_supports_lookup():
    mcp = McpToolSource(
        [McpToolDeclaration(name="a", description="d", input_schema={}, handler=_handler)]
    )
    skill = SkillToolSource([SkillDeclaration(name="b", description="d", handler=_handler)])

    registry = ToolRegistry([mcp, skill])

    assert {tool.name for tool in registry.as_list()} == {"a", "b"}
    assert registry.get("a") is not None
    assert registry.get("missing") is None


def test_registry_can_limit_tools_for_one_role_session():
    first = SkillToolSource([SkillDeclaration(name="a", description="d", handler=_handler)])
    second = SkillToolSource([SkillDeclaration(name="b", description="d", handler=_handler)])
    registry = ToolRegistry([first, second])

    registry.select_tools(["b"])

    assert [tool.name for tool in registry.as_list()] == ["b"]
    assert registry.get("a") is None
    assert registry.get("b") is not None
    assert [descriptor.name for descriptor in registry.descriptors()] == ["b"]


def test_registry_rejects_unknown_role_tool_names():
    registry = ToolRegistry([SkillToolSource([
        SkillDeclaration(name="a", description="d", handler=_handler),
    ])])

    with pytest.raises(ValueError, match="unknown tool names"):
        registry.select_tools(["missing"])


def test_empty_registry_has_no_tools():
    registry = ToolRegistry()

    assert registry.as_list() == []


def test_registry_asserts_on_duplicate_tool_names_across_sources():
    first = SkillToolSource([SkillDeclaration(name="dup", description="d", handler=_handler)])
    second = SkillToolSource([SkillDeclaration(name="dup", description="d2", handler=_handler)])

    try:
        ToolRegistry([first, second])
    except AssertionError:
        return
    raise AssertionError("expected duplicate tool names to raise")
