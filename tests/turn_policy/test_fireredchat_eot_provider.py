import pytest

from server.turn_policy.eot_classifier import EotDecision, EotRequest
from server.turn_policy.plugins.fireredchat_eot_provider import (
    FireRedChatEotProvider,
)


class RecordingProbabilityModel:
    def __init__(self, probability: float) -> None:
        self._probability = probability
        self.text: str | None = None

    def predict(self, text: str) -> float:
        self.text = text
        return self._probability


async def test_fireredchat_provider_returns_probability_without_trusting_punctuation() -> None:
    model = RecordingProbabilityModel(0.84)
    provider = FireRedChatEotProvider(model, threshold=0.6)

    evidence = await provider.evaluate(
        EotRequest(text="我还想再看看，然后。", generation=3, language="zh")
    )

    assert model.text == "我还想再看看然后"
    assert evidence.decision is EotDecision.COMPLETE
    assert evidence.probability == 0.84
    assert evidence.threshold == 0.6
    assert evidence.confidence == 0.84
    assert evidence.source == "fireredchat"
    assert evidence.inference_ms >= 0


async def test_fireredchat_provider_maps_low_probability_to_incomplete() -> None:
    provider = FireRedChatEotProvider(RecordingProbabilityModel(0.18), threshold=0.5)

    evidence = await provider.evaluate(EotRequest(text="因为我", generation=4))

    assert evidence.decision is EotDecision.INCOMPLETE
    assert evidence.confidence == pytest.approx(0.82)
