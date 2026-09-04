import pytest

from server.agent_session.in_memory_session import InMemoryDriver
from server.brain.chat_brain import ChatBrain
from server.brain.llm_clients import EchoLlmClient
from server.brain.plugins.keyword_delegation_policy import KeywordDelegationPolicy
from server.brain.router import ChatReply, DelegateToAgent, LocalConversation, Router
from server.core.turn_content import TurnContent


async def test_router_v1_default_policy_always_uses_chat_brain():
    router = Router(chat_brain=ChatBrain(EchoLlmClient()))

    response = await router.route(TurnContent(text="what's the weather", generation=5))

    assert response.text == "You said: what's the weather"
    assert response.generation == 5


async def test_decide_with_no_delegation_policy_returns_chat_reply():
    router = Router(chat_brain=ChatBrain(EchoLlmClient()))

    decision = await router.decide(TurnContent(text="what's the weather", generation=5))

    assert isinstance(decision, ChatReply)
    assert decision.response.text == "You said: what's the weather"
    assert decision.response.generation == 5


async def test_plan_returns_local_route_without_running_the_legacy_chat_brain():
    class FailingBrain:
        async def respond(self, content):
            raise AssertionError(f"legacy Brain must not run for {content.text}")

    router = Router(chat_brain=FailingBrain())

    decision = await router.plan(TurnContent(text="stream this", generation=5))

    assert isinstance(decision, LocalConversation)


async def test_decide_with_matching_delegation_policy_returns_delegate_to_agent():
    driver = InMemoryDriver()
    router = Router(
        chat_brain=ChatBrain(EchoLlmClient()),
        delegation_policy=KeywordDelegationPolicy(("delegate:",), "agent", ack_text="Looking into it."),
        drivers={"agent": driver},
    )
    content = TurnContent(text="delegate: find flights", generation=1)

    decision = await router.decide(content)

    assert isinstance(decision, DelegateToAgent)
    assert decision.ack_text == "Looking into it."
    assert decision.session is driver.sessions[0]
    assert decision.session.sent_content == content


async def test_decide_with_non_matching_delegation_policy_falls_back_to_chat():
    driver = InMemoryDriver()
    router = Router(
        chat_brain=ChatBrain(EchoLlmClient()),
        delegation_policy=KeywordDelegationPolicy(("delegate:",), "agent"),
        drivers={"agent": driver},
    )

    decision = await router.decide(TurnContent(text="hello there", generation=1))

    assert isinstance(decision, ChatReply)
    assert driver.sessions == []


async def test_decide_with_unregistered_target_agent_raises_value_error():
    router = Router(
        chat_brain=ChatBrain(EchoLlmClient()),
        delegation_policy=KeywordDelegationPolicy(("delegate:",), "unregistered-agent"),
        drivers={"agent": InMemoryDriver()},
    )

    with pytest.raises(ValueError, match="unregistered-agent"):
        await router.decide(TurnContent(text="delegate: find flights", generation=1))
