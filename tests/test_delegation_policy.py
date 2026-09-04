import pytest

from server.brain.delegation_policy import NeverDelegatePolicy
from server.brain.plugins.keyword_delegation_policy import KeywordDelegationPolicy
from server.core.turn_content import TurnContent


async def test_never_delegate_policy_never_delegates():
    policy = NeverDelegatePolicy()

    target = await policy.choose_agent(TurnContent(text="find flights", generation=1))

    assert target is None


def test_never_delegate_policy_ack_text_raises_since_it_is_never_used():
    policy = NeverDelegatePolicy()

    with pytest.raises(AssertionError):
        policy.ack_text(TurnContent(text="find flights", generation=1))


async def test_keyword_policy_delegates_on_matching_trigger():
    policy = KeywordDelegationPolicy(("帮我查一下", "delegate:"), "agent")

    target = await policy.choose_agent(TurnContent(text="帮我查一下明天的天气", generation=1))

    assert target == "agent"


async def test_keyword_policy_does_not_delegate_without_trigger():
    policy = KeywordDelegationPolicy(("帮我查一下", "delegate:"), "agent")

    target = await policy.choose_agent(TurnContent(text="hello there", generation=1))

    assert target is None


async def test_keyword_policy_ack_text_is_configurable():
    policy = KeywordDelegationPolicy(("delegate:",), "agent", ack_text="Working on it.")

    ack_text = policy.ack_text(TurnContent(text="delegate: find flights", generation=1))

    assert ack_text == "Working on it."
