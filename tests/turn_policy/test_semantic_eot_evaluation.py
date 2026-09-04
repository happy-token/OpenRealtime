import json
from collections import Counter
from pathlib import Path

from server.turn_policy.eot_classifier import EotDecision, EotEvidence
from server.turn_policy.evaluation import (
    evaluate_semantic_eot_cases,
    load_semantic_eot_cases,
)


class OrderedEvidenceProvider:
    def __init__(self, evidence: list[EotEvidence]) -> None:
        self._evidence = iter(evidence)

    async def evaluate(self, request):
        return next(self._evidence)


class FailingEvidenceProvider:
    async def evaluate(self, request):
        raise ValueError("empty provider output")


def test_load_semantic_eot_cases_preserves_context_and_labels(tmp_path) -> None:
    dataset = tmp_path / "semantic-eot.jsonl"
    rows = [
        {
            "id": "zh-context-complete-001",
            "language": "zh-CN",
            "text": "那就明天上午吧",
            "label": "complete",
            "history": [
                {"role": "assistant", "content": "周一和周二都可以，您选哪天？"}
            ],
            "category": "context_ellipsis",
            "difficulty": "medium",
            "tags": ["context"],
        },
        {
            "id": "zh-connective-incomplete-001",
            "language": "zh-CN",
            "text": "如果明天下雨的话",
            "label": "incomplete",
            "history": [],
            "category": "trailing_condition",
            "difficulty": "easy",
            "tags": ["condition"],
        },
    ]
    dataset.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    cases = load_semantic_eot_cases(dataset)

    assert [case.case_id for case in cases] == [
        "zh-context-complete-001",
        "zh-connective-incomplete-001",
    ]
    assert cases[0].expected is EotDecision.COMPLETE
    assert cases[0].context.history[0].role == "assistant"
    assert cases[0].context.history[0].content == "周一和周二都可以，您选哪天？"
    assert cases[1].expected is EotDecision.INCOMPLETE
    assert cases[1].category == "trailing_condition"


async def test_evaluate_semantic_eot_cases_reports_voice_runtime_error_rates(
    tmp_path,
) -> None:
    dataset = tmp_path / "semantic-eot.jsonl"
    rows = [
        {
            "id": f"case-{index}",
            "text": text,
            "label": label,
            "history": [],
            "category": category,
            "difficulty": "medium",
        }
        for index, (text, label, category) in enumerate(
            [
                ("帮我查天气", "complete", "query"),
                ("如果下雨的话", "incomplete", "condition"),
                ("明天上午十点", "complete", "query"),
                ("我还想问一下关于", "incomplete", "condition"),
            ],
            start=1,
        )
    ]
    dataset.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    provider = OrderedEvidenceProvider(
        [
            EotEvidence(EotDecision.COMPLETE, "stub", inference_ms=10),
            EotEvidence(EotDecision.COMPLETE, "stub", inference_ms=20),
            EotEvidence(EotDecision.INCOMPLETE, "stub", inference_ms=30),
            EotEvidence(EotDecision.INCOMPLETE, "stub", inference_ms=40),
        ]
    )

    report = await evaluate_semantic_eot_cases(
        provider, load_semantic_eot_cases(dataset)
    )

    assert report.total == 4
    assert report.accuracy == 0.5
    assert report.complete_precision == 0.5
    assert report.false_cutoff_rate == 0.5
    assert report.missed_endpoint_rate == 0.5
    assert report.latency_p50_ms == 20
    assert report.latency_p95_ms == 40
    assert report.by_category["query"].accuracy == 0.5
    assert [prediction.correct for prediction in report.predictions] == [
        True,
        False,
        False,
        True,
    ]


def test_project_chinese_evaluation_set_is_balanced_and_contextual() -> None:
    dataset = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "eot_eval"
        / "zh_semantic_completeness_v1.jsonl"
    )

    cases = load_semantic_eot_cases(dataset)

    assert len(cases) == 100
    assert Counter(case.expected for case in cases) == {
        EotDecision.COMPLETE: 50,
        EotDecision.INCOMPLETE: 50,
    }
    assert Counter(case.category for case in cases) == {
        "confirmation_backchannel": 10,
        "context_ellipsis": 10,
        "correction_supplement": 10,
        "direct_query": 10,
        "enumeration_comparison": 10,
        "long_spoken": 10,
        "spoken_disfluency": 10,
        "task_request": 10,
        "trailing_condition": 10,
        "trailing_connective": 10,
    }
    assert sum(bool(case.context.history) for case in cases) >= 20
    assert sum(case.difficulty == "hard" for case in cases) >= 20


async def test_evaluation_can_record_provider_failure_as_uncertain_and_continue(
    tmp_path,
) -> None:
    dataset = tmp_path / "semantic-eot.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "failure-case",
                "text": "如果明天下雨",
                "label": "incomplete",
                "history": [],
                "category": "condition",
                "difficulty": "medium",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = await evaluate_semantic_eot_cases(
        FailingEvidenceProvider(),
        load_semantic_eot_cases(dataset),
        continue_on_error=True,
    )

    assert report.predictions[0].predicted is EotDecision.UNCERTAIN
    assert report.predictions[0].source == "evaluation_error:ValueError"
    assert report.false_cutoff_rate == 0
