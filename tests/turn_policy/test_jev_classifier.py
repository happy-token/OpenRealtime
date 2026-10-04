from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from server.turn_policy.eot_classifier import EotContext, EotDecision, EotHistoryMessage, EotRequest
from server.turn_policy.plugins.jev_classifier import (
    EOT_CRITERIA,
    JevChoice,
    JevClient,
    JevEotClassifier,
    JevSemanticInterruptionClassifier,
)
from server.turn_policy.semantic_input import SemanticInputState, TextBoundary
from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionLabel,
    InterruptionRequest,
)
from server.turn_policy.states import DialogueState


class Choices:
    def __init__(self, label, confidence=0.99):
        self.label, self.confidence = label, confidence
        self.calls = []

    async def choose(self, **kwargs):
        self.calls.append(kwargs)
        json.dumps(kwargs["state"])
        return JevChoice(
            self.label,
            self.confidence,
            "jev-test",
            tuple((label, float(label == self.label)) for label in kwargs["criteria"]),
        )


async def test_eot_preserves_history_and_unknown_state():
    client = Choices("complete")
    result = await JevEotClassifier(client).classify_request(
        EotRequest(
            text="上海",
            generation=1,
            context=EotContext((EotHistoryMessage("assistant", "你想查哪里？"),)),
            input_state=SemanticInputState(
                dialogue_state=DialogueState.LISTEN, boundary=TextBoundary.PARTIAL
            ),
        )
    )
    assert result.decision is EotDecision.COMPLETE
    assert result.source == "jev:jev-test"
    state = client.calls[0]["state"]
    assert state["history"][0]["content"] == "你想查哪里？"
    assert state["input_state"]["speech_active"] is None
    assert state["input_state"]["dialogue_state"] == "listen"


async def test_low_confidence_eot_waits_instead_of_committing():
    result = await JevEotClassifier(Choices("complete", 0.4)).classify(
        text="从北京到", generation=1
    )
    assert result.decision is EotDecision.UNCERTAIN
    assert result.confidence == 0.4


@pytest.mark.parametrize("label", list(InterruptionLabel))
async def test_interruption_maps_all_labels_with_history_and_playback(label):
    client = Choices(label.value)
    result = await JevSemanticInterruptionClassifier(client).classify_request(
        InterruptionRequest(
            transcript="不是北京，是上海",
            assistant_text="北京天气",
            generation=1,
            boundary=InterruptionBoundary.SENTENCE_END,
            history=(EotHistoryMessage("user", "查天气"),),
        )
    )
    assert result.label is label
    assert result.confidence == 0.99
    state = client.calls[0]["state"]
    assert state["assistant_playback"] == "北京天气"
    assert state["history"][0]["content"] == "查天气"
    assert state["observation"].startswith("unknown")


def sdk_stub(monkeypatch, *, stall=False, fail=False):
    entered, closed = asyncio.Event(), asyncio.Event()
    config = {}

    class Client:
        def __init__(self, **kwargs):
            config.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.set()

        async def system_one(self, **kwargs):
            entered.set()
            if stall:
                await asyncio.Event().wait()
            if fail:
                raise ConnectionError("provider unavailable")
            return SimpleNamespace(
                model="jev-test",
                choices={
                    "decision": SimpleNamespace(
                        choice="complete",
                        confidence=0.99,
                        probabilities={label: float(label == "complete") for label in EOT_CRITERIA},
                    )
                },
            )

    monkeypatch.setitem(
        sys.modules,
        "typesafe_sdk",
        SimpleNamespace(
            AsyncTypeSafeClient=Client,
            Choice=lambda **kwargs: kwargs,
            RetryPolicy=lambda **kwargs: kwargs,
        ),
    )
    return entered, closed, config


async def test_transport_retains_probabilities_and_disables_retries(monkeypatch):
    _, closed, config = sdk_stub(monkeypatch)
    observed = []
    result = await JevClient(api_key="test", observer=observed.append).choose(
        state={"transcript": "你好"},
        instructions="test",
        criteria=EOT_CRITERIA,
    )
    assert observed == [result]
    assert dict(result.probabilities)["complete"] == 1
    assert closed.is_set()
    assert config["retry"]["max_retries"] == 0


async def test_cancel_releases_sdk_connection(monkeypatch):
    entered, closed, _ = sdk_stub(monkeypatch, stall=True)
    task = asyncio.create_task(
        JevClient(api_key="test").choose(
            state={},
            instructions="test",
            criteria=EOT_CRITERIA,
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_timeout_is_bounded_and_provider_failure_propagates(monkeypatch):
    _, closed, _ = sdk_stub(monkeypatch, stall=True)
    with pytest.raises(TimeoutError):
        await JevClient(api_key="test", timeout_s=0.02).choose(
            state={},
            instructions="test",
            criteria=EOT_CRITERIA,
        )
    assert closed.is_set()
    sdk_stub(monkeypatch, fail=True)
    with pytest.raises(ConnectionError):
        await JevClient(api_key="test").choose(state={}, instructions="test", criteria=EOT_CRITERIA)


@pytest.mark.parametrize(
    "change",
    [
        {"label": "unknown"},
        {"confidence": float("nan")},
        {"probabilities": (("complete", 1.0),)},
    ],
)
async def test_invalid_provider_result_is_not_accepted(change):
    class Bad:
        async def choose(self, **kwargs):
            return replace(
                JevChoice(
                    "complete",
                    0.99,
                    "jev-test",
                    tuple((label, float(label == "complete")) for label in EOT_CRITERIA),
                ),
                **change,
            )

    with pytest.raises(ValueError):
        await JevEotClassifier(Bad()).classify(text="你好", generation=1)


async def test_jev_adapters_drive_coordinator_yield_and_final_commit():
    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.turn_manager import (
        AsrCommitRequested,
        AssistantYieldRequested,
        ObserveAsrEvent,
        ObserveAssistantYielded,
        ObserveSystemResponseStarted,
        UserTurnCommitted,
    )
    from tests.realtime.test_coordinated_turn_manager import (
        context,
        opened,
        start,
        stop,
        take,
        text,
    )

    session = await opened(
        eot_classifier=JevEotClassifier(Choices("complete")),
        semantic_interruption_classifier=JevSemanticInterruptionClassifier(Choices("correction")),
    )
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(context=context(), response_id="old"))
        await start(session)
        await text(session, "不是北京，是上海")
        await stop(session)
        event = await take(stream, AssistantYieldRequested)
        assert event.context.response_id == "old"
        await session.send(ObserveAssistantYielded(context=event.context))
        await take(stream, AsrCommitRequested)
        await session.send(
            ObserveAsrEvent(
                event=AsrTranscriptFinal(
                    context=context(),
                    revision=2,
                    text="不是北京，是上海",
                    reason="final",
                )
            )
        )
        event = await take(stream, UserTurnCommitted)
        assert event.text == "不是北京，是上海"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("threshold,discard", [(0.95, False), (0.85, True)])
async def test_jev_backchannel_threshold_controls_actual_yield(threshold, discard):
    from server.realtime.capabilities.turn_manager import (
        AsrDiscardRequested,
        AssistantYieldRequested,
        ObserveSystemResponseStarted,
    )
    from server.turn_policy.coordination import DefaultTurnCoordinationPolicy
    from tests.realtime.test_coordinated_turn_manager import (
        context,
        opened,
        start,
        stop,
        take,
        text,
    )

    session = await opened(
        eot_classifier=JevEotClassifier(Choices("complete")),
        semantic_interruption_classifier=JevSemanticInterruptionClassifier(
            Choices("backchannel", 0.88)
        ),
        coordination_policy_factory=lambda: DefaultTurnCoordinationPolicy(
            backchannel_confidence=threshold
        ),
    )
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(context=context(), response_id="old"))
        await start(session)
        await text(session, "嗯，我在听，你继续讲")
        await stop(session)
        await take(stream, AsrDiscardRequested if discard else AssistantYieldRequested)
        if discard:
            assert session.snapshot().response_id == "old"
    finally:
        await stream.aclose()
        await session.close()
