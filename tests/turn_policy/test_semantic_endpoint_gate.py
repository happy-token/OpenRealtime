import asyncio

from server.turn_policy.eot_classifier import EotClassification, EotDecision
from server.turn_policy.semantic_endpoint import (
    EndpointActivity,
    EndpointCandidate,
    EndpointResolution,
    EndpointStop,
    SemanticEndpointGate,
)


class BlockingClassifier:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def classify(self, *, text: str, generation: int) -> EotClassification:
        del text, generation
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FixedClassifier:
    def __init__(self, result: EotClassification | EotDecision) -> None:
        self.result = result
        self.calls = 0

    async def classify(
        self, *, text: str, generation: int
    ) -> EotClassification | EotDecision:
        del text, generation
        self.calls += 1
        return self.result


def candidate() -> EndpointCandidate:
    return EndpointCandidate(text="我想", generation=3, transcript_revision=7)


async def test_sentence_end_precomputes_but_does_not_commit_before_stop() -> None:
    classifier = FixedClassifier(EotDecision.COMPLETE)
    gate = SemanticEndpointGate(classifier)
    activity = EndpointActivity()
    stop = EndpointStop()

    resolution_task = asyncio.create_task(gate.resolve(candidate(), activity, stop))
    for _ in range(3):
        if classifier.calls:
            break
        await asyncio.sleep(0)

    assert classifier.calls == 1
    assert resolution_task.done() is False

    stop.confirm("vad_stop")
    outcome = await resolution_task

    assert outcome.resolution is EndpointResolution.COMMIT
    assert outcome.stop_source == "vad_stop"


async def test_new_activity_wins_and_cancels_semantic_judgement() -> None:
    classifier = BlockingClassifier()
    gate = SemanticEndpointGate(classifier)
    activity = EndpointActivity()
    stop = EndpointStop()

    resolution_task = asyncio.create_task(gate.resolve(candidate(), activity, stop))
    await classifier.started.wait()
    activity.invalidate("vad_speech")

    outcome = await resolution_task
    assert outcome.resolution is EndpointResolution.DEFER_ACTIVITY
    assert classifier.cancelled is True


async def test_completed_judgement_survives_vad_restart_until_fresh_stop() -> None:
    classifier = FixedClassifier(EotDecision.COMPLETE)
    gate = SemanticEndpointGate(classifier)
    activity = EndpointActivity()
    stop = EndpointStop()

    resolution_task = asyncio.create_task(gate.resolve(candidate(), activity, stop))
    for _ in range(3):
        if classifier.calls:
            break
        await asyncio.sleep(0)

    activity.invalidate("vad_speech")
    await asyncio.sleep(0)

    assert resolution_task.done() is False
    stop.confirm("asr_idle")
    outcome = await resolution_task

    assert outcome.resolution is EndpointResolution.COMMIT
    assert outcome.stop_source == "asr_idle"
    assert classifier.calls == 1


async def test_asr_increment_supersedes_pending_vad_only_recovery() -> None:
    classifier = FixedClassifier(EotDecision.COMPLETE)
    gate = SemanticEndpointGate(classifier)
    activity = EndpointActivity()
    stop = EndpointStop()

    resolution_task = asyncio.create_task(gate.resolve(candidate(), activity, stop))
    for _ in range(3):
        if classifier.calls:
            break
        await asyncio.sleep(0)

    activity.invalidate("vad_speech")
    activity.invalidate("asr_increment")
    outcome = await resolution_task

    assert outcome.resolution is EndpointResolution.DEFER_ACTIVITY
    assert activity.reason == "asr_increment"
    assert classifier.calls == 1


async def test_incomplete_is_returned_only_after_stop_for_bounded_hold() -> None:
    classifier = FixedClassifier(
        EotClassification(
            decision=EotDecision.INCOMPLETE,
            confidence=0.93,
            source="llm",
        )
    )
    gate = SemanticEndpointGate(classifier)
    stop = EndpointStop()
    resolution_task = asyncio.create_task(
        gate.resolve(candidate(), EndpointActivity(), stop)
    )
    await asyncio.sleep(0)

    assert resolution_task.done() is False
    stop.confirm("asr_idle")
    outcome = await resolution_task

    assert outcome.resolution is EndpointResolution.HOLD_INCOMPLETE
    assert outcome.classification.confidence == 0.93
    assert outcome.stop_source == "asr_idle"


async def test_uncertain_preserves_model_wait_hint() -> None:
    classifier = FixedClassifier(
        EotClassification(
            decision=EotDecision.UNCERTAIN,
            confidence=0.51,
            wait_ms=180,
            source="llm",
        )
    )
    gate = SemanticEndpointGate(classifier)
    stop = EndpointStop()
    stop.confirm("vad_stop")

    outcome = await gate.resolve(candidate(), EndpointActivity(), stop)

    assert outcome.resolution is EndpointResolution.HOLD_UNCERTAIN
    assert outcome.classification.wait_ms == 180


async def test_uncertain_model_wait_hint_is_clamped_to_liveness_ceiling() -> None:
    classifier = FixedClassifier(
        EotClassification(
            decision=EotDecision.UNCERTAIN,
            confidence=0.4,
            wait_ms=30_000,
            source="llm",
        )
    )
    gate = SemanticEndpointGate(classifier)
    stop = EndpointStop()
    stop.confirm("vad_stop")

    outcome = await gate.resolve(candidate(), EndpointActivity(), stop)

    assert outcome.classification.wait_ms == 400


async def test_classifier_timeout_degrades_to_bounded_uncertain() -> None:
    classifier = BlockingClassifier()
    gate = SemanticEndpointGate(
        classifier,
        classifier_timeout_ms=1,
        uncertain_wait_ms=25,
    )
    stop = EndpointStop()
    stop.confirm("vad_stop")

    outcome = await gate.resolve(candidate(), EndpointActivity(), stop)

    assert outcome.resolution is EndpointResolution.HOLD_UNCERTAIN
    assert outcome.classification.wait_ms == 25
    assert outcome.classification.source == "classifier_error"
    assert outcome.error is not None
    assert classifier.cancelled is True


async def test_no_classifier_still_requires_stop() -> None:
    gate = SemanticEndpointGate(None)
    stop = EndpointStop()
    resolution_task = asyncio.create_task(
        gate.resolve(candidate(), EndpointActivity(), stop)
    )
    await asyncio.sleep(0)

    assert resolution_task.done() is False
    stop.confirm("vad_stop")

    assert (await resolution_task).resolution is EndpointResolution.COMMIT
