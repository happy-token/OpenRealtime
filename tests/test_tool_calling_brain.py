import pytest

from server.brain.llm_clients import EchoToolCallingLlmClient, FinalText, ToolCallRequest
from server.brain.tool_calling_brain import DEFAULT_SYSTEM_PROMPT, ToolCallingBrain
from server.core.turn_content import TurnContent
from server.tools.registry import ToolRegistry
from server.tools.skill_source import SkillDeclaration, SkillToolSource


def _registry_with_time_tool(handler):
    source = SkillToolSource([SkillDeclaration(name="get_current_time", description="d", handler=handler)])
    return ToolRegistry([source])


async def test_echo_tool_calling_llm_client_passes_through_when_no_tool_mentioned():
    client = EchoToolCallingLlmClient()

    result = await client.complete(system_prompt="s", user_text="hello", tools=[])

    assert result == FinalText("You said: hello")


async def test_echo_tool_calling_llm_client_requests_tool_mentioned_by_name():
    client = EchoToolCallingLlmClient()
    registry = _registry_with_time_tool(lambda args: "unused")

    result = await client.complete(
        system_prompt="s", user_text="please get_current_time now", tools=registry.as_list()
    )

    assert result == ToolCallRequest(name="get_current_time", arguments={})


async def test_echo_tool_calling_llm_client_finalizes_from_tool_result():
    client = EchoToolCallingLlmClient()

    result = await client.complete(
        system_prompt="s", user_text="please get_current_time now", tools=[], tool_result="12:00"
    )

    assert result == FinalText("Tool said: 12:00")


async def test_tool_calling_brain_returns_final_text_unchanged_when_no_tool_call():
    registry = ToolRegistry()
    brain = ToolCallingBrain(EchoToolCallingLlmClient(), registry)

    response = await brain.respond(TurnContent(text="hello", generation=1))

    assert response.text == "You said: hello"
    assert response.generation == 1


async def test_tool_calling_brain_resolves_the_active_persona_for_each_turn():
    seen_prompts: list[str] = []
    active = {"prompt": "Persona A"}

    class RecordingClient:
        async def complete(self, *, system_prompt, user_text, tools, tool_result=None):
            del user_text, tools, tool_result
            seen_prompts.append(system_prompt)
            return FinalText("ok")

    brain = ToolCallingBrain(
        RecordingClient(),
        ToolRegistry(),
        system_prompt="BASE",
        system_prompt_transform=lambda base: f"{base}\n\n{active['prompt']}",
    )

    await brain.respond(TurnContent(text="first", generation=1))
    active["prompt"] = "Persona B"
    await brain.respond(TurnContent(text="second", generation=2))

    assert seen_prompts == ["BASE\n\nPersona A", "BASE\n\nPersona B"]


async def test_tool_calling_brain_invokes_handler_and_returns_round_tripped_text():
    seen_arguments: list[dict] = []

    async def handler(arguments: dict) -> str:
        seen_arguments.append(arguments)
        return "12:00"

    registry = _registry_with_time_tool(handler)
    brain = ToolCallingBrain(EchoToolCallingLlmClient(), registry)

    response = await brain.respond(TurnContent(text="please get_current_time now", generation=3))

    assert response.text == "Tool said: 12:00"
    assert response.generation == 3
    assert seen_arguments == [{}]


async def test_tool_calling_brain_asserts_on_unknown_tool_name():
    class BadLlmClient:
        async def complete(self, *, system_prompt, user_text, tools, tool_result=None):
            return ToolCallRequest(name="does_not_exist", arguments={})

    brain = ToolCallingBrain(BadLlmClient(), ToolRegistry())

    with pytest.raises(AssertionError):
        await brain.respond(TurnContent(text="hi", generation=1))


async def test_tool_calling_brain_executes_bounded_sequential_tool_calls():
    calls: list[str] = []

    class SequentialClient:
        async def complete(self, *, system_prompt, user_text, tools, tool_result=None):
            del system_prompt, user_text, tools
            if tool_result is None:
                return ToolCallRequest(name="get_current_time", arguments={})
            calls.append(tool_result)
            if len(calls) == 1:
                return ToolCallRequest(name="get_current_time", arguments={})
            return FinalText("done")

    async def handler(arguments: dict) -> str:
        del arguments
        return f"result-{len(calls) + 1}"

    brain = ToolCallingBrain(SequentialClient(), _registry_with_time_tool(handler))

    response = await brain.respond(TurnContent(text="chain", generation=1))

    assert response.text == "done"
    assert calls == ["result-1", "result-2"]


def test_default_prompt_routes_realtime_queries_to_minimal_tools():
    assert "fewest tool calls" in DEFAULT_SYSTEM_PROMPT
    assert "current date or time" in DEFAULT_SYSTEM_PROMPT
    assert "weather" in DEFAULT_SYSTEM_PROMPT
    assert "search_web directly" in DEFAULT_SYSTEM_PROMPT
