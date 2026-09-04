from __future__ import annotations

import asyncio

import pytest

from server.turn_policy.semantic_interruption import (
    InterruptionBoundary,
    InterruptionCandidate,
    InterruptionClassification,
    InterruptionLabel,
    InterruptionRevisionScheduler,
    SemanticInterruptionGate,
    match_interruption_rule,
    parse_interruption_classification,
)


def candidate(
    text: str,
    revision: int,
    *,
    boundary: InterruptionBoundary = InterruptionBoundary.PARTIAL,
) -> InterruptionCandidate:
    return InterruptionCandidate(
        text=text,
        generation=7,
        transcript_revision=revision,
        boundary=boundary,
    )


class RecordingClassifier:
    def __init__(self, result: InterruptionClassification) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        self.calls.append(
            {
                "assistant_text": assistant_text,
                "transcript": transcript,
                "boundary": boundary,
                "generation": generation,
            }
        )
        return self.result


class LatestWinsClassifier:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.first_started = asyncio.Event()
        self.first_cancelled = False

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del assistant_text, boundary, generation
        self.calls.append(transcript)
        if len(self.calls) == 1:
            self.first_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.first_cancelled = True
                raise
        return InterruptionClassification(InterruptionLabel.INTERRUPT, 0.95)


class FailingClassifier:
    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del assistant_text, transcript, boundary, generation
        raise RuntimeError("classifier unavailable")


class BlockingClassifier:
    def __init__(self) -> None:
        self.cancelled = False

    async def classify(
        self,
        *,
        assistant_text: str,
        transcript: str,
        boundary: InterruptionBoundary,
        generation: int,
    ) -> InterruptionClassification:
        del assistant_text, transcript, boundary, generation
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_rules_are_exact_and_short_boundary_stop_waits_for_stability() -> None:
    assert match_interruption_rule("别说了", boundary=InterruptionBoundary.PARTIAL).label is InterruptionLabel.STOP
    assert match_interruption_rule("嗯。", boundary=InterruptionBoundary.PARTIAL).label is InterruptionLabel.BACKCHANNEL
    assert match_interruption_rule("停", boundary=InterruptionBoundary.PARTIAL) is None
    assert (
        match_interruption_rule(
            "停",
            boundary=InterruptionBoundary.PARTIAL,
            stable=True,
        ).label
        is InterruptionLabel.STOP
    )
    assert match_interruption_rule("停电了吗", boundary=InterruptionBoundary.SENTENCE_END) is None
    assert match_interruption_rule("我是在引用‘别说了’", boundary=InterruptionBoundary.SENTENCE_END) is None


def test_strict_json_parser_rejects_extra_fields_and_bad_confidence() -> None:
    parsed = parse_interruption_classification('{"label":"correction","confidence":0.91}')
    assert parsed == InterruptionClassification(InterruptionLabel.CORRECTION, 0.91)

    with pytest.raises(ValueError):
        parse_interruption_classification(
            '{"label":"interrupt","confidence":0.9,"reason":"extra"}'
        )
    with pytest.raises(ValueError):
        parse_interruption_classification('{"label":"interrupt","confidence":1.5}')


def test_scheduler_does_not_duplicate_identical_partial_and_stable_final_supersedes() -> None:
    scheduler = InterruptionRevisionScheduler(partial_chars=5, idle_ms=100)

    first = scheduler.observe(candidate("请帮我查找", 1), now_ms=0)
    duplicate = scheduler.observe(candidate("请帮我查找", 1), now_ms=50)
    final = scheduler.observe(
        candidate("请帮我查找", 1, boundary=InterruptionBoundary.SENTENCE_END),
        now_ms=60,
    )

    assert first is not None and first.reason == "chars"
    assert duplicate is None
    assert final is not None and final.reason == "sentence_end" and final.stable is True
    assert scheduler.on_idle(now_ms=500) is None


async def test_rule_fast_path_emits_immediately_without_spawning_model() -> None:
    classifier = RecordingClassifier(
        InterruptionClassification(InterruptionLabel.BACKCHANNEL, 1.0)
    )
    observed = []
    gate = SemanticInterruptionGate(classifier, observer=observed.append)
    await gate.begin(generation=7, assistant_text="正在播报的回答")

    verdict = await gate.observe(candidate("别说了", 1))

    assert verdict is not None
    assert verdict.label is InterruptionLabel.STOP
    assert verdict.source == "rule"
    assert observed == [verdict]
    assert classifier.calls == []
    await gate.close()


async def test_latest_revision_cancels_old_model_and_only_latest_result_is_observed() -> None:
    classifier = LatestWinsClassifier()
    observed = []
    gate = SemanticInterruptionGate(
        classifier,
        observer=observed.append,
        partial_chars=5,
        idle_ms=100,
    )
    await gate.begin(generation=7, assistant_text="旧回答")

    await gate.observe(candidate("请帮我查找", 1))
    await classifier.first_started.wait()
    await gate.observe(candidate("请帮我查找明天天气一下", 2))
    await gate.wait()

    assert classifier.first_cancelled is True
    assert classifier.calls == ["请帮我查找", "请帮我查找明天天气一下"]
    assert [item.candidate.transcript_revision for item in observed] == [2]
    assert observed[0].label is InterruptionLabel.INTERRUPT
    await gate.close()


async def test_unscheduled_partial_revision_does_not_restart_model_request() -> None:
    classifier = LatestWinsClassifier()
    gate = SemanticInterruptionGate(
        classifier,
        partial_chars=5,
        idle_ms=100,
    )
    await gate.begin(generation=7, assistant_text="旧回答")

    await gate.observe(candidate("请帮我查找", 1))
    await classifier.first_started.wait()
    await gate.observe(candidate("请帮我查找天", 2))
    await asyncio.sleep(0)

    assert classifier.first_cancelled is False
    assert classifier.calls == ["请帮我查找"]

    await gate.resolve(
        candidate(
            "请帮我查找天",
            2,
            boundary=InterruptionBoundary.SENTENCE_END,
        )
    )

    assert classifier.first_cancelled is True
    assert classifier.calls == ["请帮我查找", "请帮我查找天"]
    await gate.close()


async def test_duplicate_revision_never_spawns_a_second_classification_task() -> None:
    classifier = RecordingClassifier(
        InterruptionClassification(InterruptionLabel.INTERRUPT, 0.95)
    )
    gate = SemanticInterruptionGate(classifier, partial_chars=5)
    await gate.begin(generation=7, assistant_text="回答")

    item = candidate("请帮我查找", 1)
    await gate.observe(item)
    await gate.observe(item)
    await gate.wait()

    assert len(classifier.calls) == 1
    await gate.close()


async def test_low_confidence_stop_is_uncertain_but_model_failure_fails_open() -> None:
    low_confidence = RecordingClassifier(
        InterruptionClassification(InterruptionLabel.STOP, 0.2)
    )
    low_gate = SemanticInterruptionGate(low_confidence, partial_chars=1)
    await low_gate.begin(generation=7, assistant_text="回答")
    await low_gate.observe(candidate("换一个", 1))
    await low_gate.wait()

    assert low_gate.latest is not None
    assert low_gate.latest.label is InterruptionLabel.UNCERTAIN
    assert low_gate.latest.source == "model"
    await low_gate.close()

    failed_gate = SemanticInterruptionGate(FailingClassifier(), partial_chars=1)
    await failed_gate.begin(generation=7, assistant_text="回答")
    await failed_gate.observe(candidate("换一个问题", 1))
    await failed_gate.wait()

    assert failed_gate.latest is not None
    assert failed_gate.latest.label is InterruptionLabel.INTERRUPT
    assert failed_gate.latest.source == "fallback"
    await failed_gate.close()


async def test_classifier_timeout_is_bounded_and_fails_open_for_non_empty_text() -> None:
    classifier = BlockingClassifier()
    gate = SemanticInterruptionGate(
        classifier,
        partial_chars=1,
        classifier_timeout_ms=5,
    )
    await gate.begin(generation=7, assistant_text="回答")

    await gate.observe(candidate("换个问题", 1))
    await gate.wait()

    assert classifier.cancelled is True
    assert gate.latest is not None
    assert gate.latest.label is InterruptionLabel.INTERRUPT
    assert gate.latest.source == "fallback"
    await gate.close()
