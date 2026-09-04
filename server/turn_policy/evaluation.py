"""Reusable evaluation support for semantic end-of-turn providers."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from server.turn_policy.eot_classifier import (
    EotContext,
    EotDecision,
    EotEvidence,
    EotEvidenceProvider,
    EotHistoryMessage,
    EotRequest,
)


@dataclass(frozen=True, slots=True)
class SemanticEotCase:
    """One curated semantic-completeness decision with optional dialogue context."""

    case_id: str
    text: str
    expected: EotDecision
    context: EotContext
    language: str
    category: str
    difficulty: Literal["easy", "medium", "hard"]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticEotPrediction:
    case_id: str
    category: str
    expected: EotDecision
    predicted: EotDecision
    probability: float | None
    inference_ms: float
    source: str

    @property
    def correct(self) -> bool:
        return self.predicted is self.expected


@dataclass(frozen=True, slots=True)
class SemanticEotMetrics:
    total: int
    accuracy: float
    complete_precision: float
    false_cutoff_rate: float
    missed_endpoint_rate: float


@dataclass(frozen=True, slots=True)
class SemanticEotReport:
    total: int
    accuracy: float
    complete_precision: float
    false_cutoff_rate: float
    missed_endpoint_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    by_category: dict[str, SemanticEotMetrics]
    predictions: tuple[SemanticEotPrediction, ...]


def load_semantic_eot_cases(path: str | Path) -> tuple[SemanticEotCase, ...]:
    """Load the project JSONL format and return immutable evaluation cases."""

    dataset_path = Path(path)
    cases: list[SemanticEotCase] = []
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
            history = tuple(
                EotHistoryMessage(role=message["role"], content=message["content"])
                for message in row.get("history", [])
            )
            expected = EotDecision(row["label"])
            if expected is EotDecision.UNCERTAIN:
                raise ValueError("evaluation labels must be complete or incomplete")
            cases.append(
                SemanticEotCase(
                    case_id=row["id"],
                    text=row["text"],
                    expected=expected,
                    context=EotContext(history=history),
                    language=row.get("language", "zh-CN"),
                    category=row["category"],
                    difficulty=row["difficulty"],
                    tags=tuple(row.get("tags", [])),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid semantic EOT dataset row {line_number}: {error}"
            ) from error
    if not cases:
        raise ValueError("semantic EOT dataset must contain at least one case")
    identifiers = [case.case_id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("semantic EOT dataset case ids must be unique")
    return tuple(cases)


async def evaluate_semantic_eot_cases(
    provider: EotEvidenceProvider,
    cases: tuple[SemanticEotCase, ...],
    *,
    continue_on_error: bool = False,
) -> SemanticEotReport:
    """Evaluate a provider sequentially so latency numbers remain comparable."""

    if not cases:
        raise ValueError("semantic EOT evaluation requires at least one case")
    predictions: list[SemanticEotPrediction] = []
    for generation, case in enumerate(cases, start=1):
        started_at = time.perf_counter()
        try:
            evidence = await provider.evaluate(
                EotRequest(
                    text=case.text,
                    generation=generation,
                    context=case.context,
                    language=case.language,
                )
            )
        except Exception as error:
            if not continue_on_error:
                raise
            evidence = EotEvidence(
                decision=EotDecision.UNCERTAIN,
                source=f"evaluation_error:{type(error).__name__}",
                inference_ms=(time.perf_counter() - started_at) * 1000,
            )
        predictions.append(
            SemanticEotPrediction(
                case_id=case.case_id,
                category=case.category,
                expected=case.expected,
                predicted=evidence.decision,
                probability=evidence.probability,
                inference_ms=evidence.inference_ms,
                source=evidence.source,
            )
        )

    overall = _metrics(predictions)
    by_category = {
        category: _metrics(
            [prediction for prediction in predictions if prediction.category == category]
        )
        for category in sorted({prediction.category for prediction in predictions})
    }
    latencies = sorted(prediction.inference_ms for prediction in predictions)
    return SemanticEotReport(
        total=overall.total,
        accuracy=overall.accuracy,
        complete_precision=overall.complete_precision,
        false_cutoff_rate=overall.false_cutoff_rate,
        missed_endpoint_rate=overall.missed_endpoint_rate,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        by_category=by_category,
        predictions=tuple(predictions),
    )


def _metrics(predictions: list[SemanticEotPrediction]) -> SemanticEotMetrics:
    complete = [
        prediction
        for prediction in predictions
        if prediction.expected is EotDecision.COMPLETE
    ]
    incomplete = [
        prediction
        for prediction in predictions
        if prediction.expected is EotDecision.INCOMPLETE
    ]
    correct = sum(prediction.correct for prediction in predictions)
    predicted_complete = [
        prediction
        for prediction in predictions
        if prediction.predicted is EotDecision.COMPLETE
    ]
    true_complete = sum(
        prediction.expected is EotDecision.COMPLETE
        for prediction in predicted_complete
    )
    false_cutoffs = sum(
        prediction.predicted is EotDecision.COMPLETE for prediction in incomplete
    )
    missed_endpoints = sum(
        prediction.predicted is not EotDecision.COMPLETE for prediction in complete
    )
    return SemanticEotMetrics(
        total=len(predictions),
        accuracy=correct / len(predictions),
        complete_precision=(
            true_complete / len(predicted_complete) if predicted_complete else 0.0
        ),
        false_cutoff_rate=false_cutoffs / len(incomplete) if incomplete else 0.0,
        missed_endpoint_rate=missed_endpoints / len(complete) if complete else 0.0,
    )


def _percentile(values: list[float], percentile: int) -> float:
    index = max(0, math.ceil(percentile / 100 * len(values)) - 1)
    return values[index]
