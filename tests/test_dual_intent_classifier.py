from server.turn_policy.dual_intent import (
    DefaultDualIntentClassifier,
    DefaultDualIntentClassifierConfig,
    DualIntent,
)
from server.turn_policy.plugins.llm_dual_intent_classifier import LlmDualIntentClassifier


class StubLlmClient:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.last_call: dict | None = None
        self.call_count = 0

    async def complete(self, *, system_prompt: str, user_text: str) -> str:
        self.call_count += 1
        self.last_call = {"system_prompt": system_prompt, "user_text": user_text}
        return self._reply


class SpyDualIntentClassifier:
    def __init__(self, intent: DualIntent) -> None:
        self._intent = intent
        self.last_call: dict | None = None

    async def classify(self, *, generation: int, overlap_ms: float, text: str) -> DualIntent:
        self.last_call = {"generation": generation, "overlap_ms": overlap_ms, "text": text}
        return self._intent


async def test_overlap_below_threshold_reads_as_backchannel():
    classifier = DefaultDualIntentClassifier()

    intent = await classifier.classify(generation=1, overlap_ms=200.0, text="")

    assert intent is DualIntent.BACKCHANNEL


async def test_overlap_at_threshold_reads_as_floor_claim():
    classifier = DefaultDualIntentClassifier()

    intent = await classifier.classify(generation=1, overlap_ms=800.0, text="")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_overlap_above_threshold_reads_as_floor_claim():
    classifier = DefaultDualIntentClassifier()

    intent = await classifier.classify(generation=1, overlap_ms=5000.0, text="")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_custom_threshold_is_honored():
    classifier = DefaultDualIntentClassifier(DefaultDualIntentClassifierConfig(floor_claim_threshold_ms=100.0))

    intent = await classifier.classify(generation=1, overlap_ms=150.0, text="")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_text_is_ignored_regardless_of_content():
    classifier = DefaultDualIntentClassifier()

    intent = await classifier.classify(generation=1, overlap_ms=200.0, text="等一下我有问题")

    assert intent is DualIntent.BACKCHANNEL


async def test_stop_reply_maps_to_floor_claim():
    classifier = LlmDualIntentClassifier(StubLlmClient("stop 0.95"))

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="actually never mind")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_correction_reply_maps_to_floor_claim():
    classifier = LlmDualIntentClassifier(StubLlmClient("correction 0.9"))

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="no I meant tomorrow")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_interrupt_reply_maps_to_floor_claim():
    classifier = LlmDualIntentClassifier(StubLlmClient("interrupt 0.9"))

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="actually can you also")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_backchannel_reply_maps_to_backchannel():
    classifier = LlmDualIntentClassifier(StubLlmClient("backchannel"))

    intent = await classifier.classify(generation=1, overlap_ms=5000.0, text="mmhmm")

    assert intent is DualIntent.BACKCHANNEL


async def test_ignore_reply_delegates_to_fallback_with_original_args():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(StubLlmClient("ignore"), fallback=fallback)

    intent = await classifier.classify(generation=3, overlap_ms=250.0, text="uh")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call == {"generation": 3, "overlap_ms": 250.0, "text": "uh"}


async def test_uncertain_reply_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.FLOOR_CLAIM)
    classifier = LlmDualIntentClassifier(StubLlmClient("uncertain"), fallback=fallback)

    intent = await classifier.classify(generation=1, overlap_ms=250.0, text="hmm well")

    assert intent is DualIntent.FLOOR_CLAIM
    assert fallback.last_call is not None


async def test_garbage_reply_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(StubLlmClient("¯\\_(ツ)_/¯"), fallback=fallback)

    intent = await classifier.classify(generation=1, overlap_ms=250.0, text="garbled")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call is not None


async def test_empty_reply_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(StubLlmClient(""), fallback=fallback)

    intent = await classifier.classify(generation=1, overlap_ms=250.0, text="some text")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call is not None


async def test_no_fallback_configured_uses_default_duration_heuristic():
    classifier = LlmDualIntentClassifier(StubLlmClient("uncertain"))

    intent = await classifier.classify(generation=1, overlap_ms=5000.0, text="hmm")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_empty_text_never_calls_llm_and_uses_fallback():
    llm_client = StubLlmClient("stop")
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(llm_client, fallback=fallback)

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="")

    assert intent is DualIntent.BACKCHANNEL
    assert llm_client.call_count == 0
    assert fallback.last_call == {"generation": 1, "overlap_ms": 100.0, "text": ""}


async def test_reply_is_case_and_whitespace_insensitive():
    classifier = LlmDualIntentClassifier(StubLlmClient("  STOP\n 0.9"))

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="anything else")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_classify_forwards_text_as_user_text_to_llm_client():
    llm_client = StubLlmClient("backchannel")
    classifier = LlmDualIntentClassifier(llm_client)

    await classifier.classify(generation=1, overlap_ms=100.0, text="mmhmm go on")

    assert llm_client.last_call is not None
    assert llm_client.last_call["user_text"] == "mmhmm go on"


async def test_stop_phrase_short_circuits_to_floor_claim_without_calling_llm():
    llm_client = StubLlmClient("backchannel")
    classifier = LlmDualIntentClassifier(llm_client)

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="wait, hold on a second")

    assert intent is DualIntent.FLOOR_CLAIM
    assert llm_client.call_count == 0


async def test_stop_phrase_match_is_case_insensitive():
    llm_client = StubLlmClient("backchannel")
    classifier = LlmDualIntentClassifier(llm_client)

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="STOP please")

    assert intent is DualIntent.FLOOR_CLAIM
    assert llm_client.call_count == 0


async def test_stop_phrases_can_be_disabled():
    llm_client = StubLlmClient("backchannel")
    classifier = LlmDualIntentClassifier(llm_client, stop_phrases=())

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="wait a moment")

    assert intent is DualIntent.BACKCHANNEL
    assert llm_client.call_count == 1


async def test_low_confidence_stop_reply_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(
        StubLlmClient("stop 0.3"), fallback=fallback, stop_phrases=()
    )

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="actually never mind")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call is not None


async def test_missing_confidence_token_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(
        StubLlmClient("correction"), fallback=fallback, stop_phrases=()
    )

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="no I meant tomorrow")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call is not None


async def test_unparseable_confidence_token_delegates_to_fallback():
    fallback = SpyDualIntentClassifier(DualIntent.BACKCHANNEL)
    classifier = LlmDualIntentClassifier(
        StubLlmClient("interrupt not-a-number"), fallback=fallback, stop_phrases=()
    )

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="actually can you also")

    assert intent is DualIntent.BACKCHANNEL
    assert fallback.last_call is not None


async def test_confidence_at_threshold_maps_to_floor_claim():
    classifier = LlmDualIntentClassifier(StubLlmClient("stop 0.8"), stop_phrases=())

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="actually never mind")

    assert intent is DualIntent.FLOOR_CLAIM


async def test_backchannel_reply_does_not_require_confidence():
    classifier = LlmDualIntentClassifier(StubLlmClient("backchannel"))

    intent = await classifier.classify(generation=1, overlap_ms=100.0, text="mmhmm")

    assert intent is DualIntent.BACKCHANNEL
