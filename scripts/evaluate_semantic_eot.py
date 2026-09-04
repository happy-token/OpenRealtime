#!/usr/bin/env python3
"""Benchmark the local FireRedChat turn detector on the project dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from server.turn_policy.evaluation import (
    SemanticEotReport,
    evaluate_semantic_eot_cases,
    load_semantic_eot_cases,
)
from server.turn_policy.plugins.classifier_eot_evidence_provider import (
    ClassifierEotEvidenceProvider,
)
from server.turn_policy.plugins.fireredchat_eot_provider import (
    FireRedChatEotProvider,
    FireRedChatOnnxModel,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "eot_eval" / "zh_semantic_completeness_v1.jsonl"
DEFAULT_MODEL_DIR = ROOT / "models" / "fireredchat-turn-detector"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate FireRedChat semantic end-of-turn accuracy and latency."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--intra-op-threads", type=int, default=2)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="evaluate the configured runtime strategy, including LLM fallback",
    )
    parser.add_argument("--output", type=Path)
    return parser


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _report_payload(report: SemanticEotReport, *, threshold: float) -> dict:
    fast_predictions = [
        prediction
        for prediction in report.predictions
        if prediction.source.startswith("fast_complete:")
    ]
    fast_complete_count = len(fast_predictions)
    return {
        "threshold": threshold,
        "total": report.total,
        "accuracy": report.accuracy,
        "complete_precision": report.complete_precision,
        "false_cutoff_rate": report.false_cutoff_rate,
        "missed_endpoint_rate": report.missed_endpoint_rate,
        "latency_p50_ms": report.latency_p50_ms,
        "latency_p95_ms": report.latency_p95_ms,
        "fast_complete_count": fast_complete_count,
        "fast_complete_precision": (
            sum(prediction.correct for prediction in fast_predictions)
            / fast_complete_count
            if fast_complete_count
            else 0.0
        ),
        "fallback_count": report.total - fast_complete_count,
        "provider_error_count": sum(
            prediction.source.startswith("evaluation_error:")
            for prediction in report.predictions
        ),
        "by_category": {
            category: {
                "total": metrics.total,
                "accuracy": metrics.accuracy,
                "complete_precision": metrics.complete_precision,
                "false_cutoff_rate": metrics.false_cutoff_rate,
                "missed_endpoint_rate": metrics.missed_endpoint_rate,
            }
            for category, metrics in report.by_category.items()
        },
        "predictions": [
            {
                "id": prediction.case_id,
                "category": prediction.category,
                "expected": prediction.expected.value,
                "predicted": prediction.predicted.value,
                "correct": prediction.correct,
                "probability": prediction.probability,
                "inference_ms": prediction.inference_ms,
                "source": prediction.source,
            }
            for prediction in report.predictions
        ],
    }


async def _run(args: argparse.Namespace) -> SemanticEotReport:
    cases = load_semantic_eot_cases(args.dataset)
    if args.runtime:
        from demos import voice_web_server

        classifier = voice_web_server._build_eot_classifier(
            voice_web_server._build_llm_client()
        )
        if classifier is None:
            raise RuntimeError("configured runtime has no semantic EOT classifier")
        return await evaluate_semantic_eot_cases(
            ClassifierEotEvidenceProvider(classifier),
            cases,
            continue_on_error=True,
        )
    model = FireRedChatOnnxModel(
        args.model_dir,
        language="chinese",
        intra_op_threads=args.intra_op_threads,
    )
    provider = FireRedChatEotProvider(model, threshold=args.threshold)
    return await evaluate_semantic_eot_cases(provider, cases)


def main() -> None:
    args = _parser().parse_args()
    report = asyncio.run(_run(args))
    print(f"cases: {report.total}")
    print(f"accuracy: {_percentage(report.accuracy)}")
    print(f"complete precision: {_percentage(report.complete_precision)}")
    print(f"false cutoff rate: {_percentage(report.false_cutoff_rate)}")
    print(f"missed endpoint rate: {_percentage(report.missed_endpoint_rate)}")
    print(
        f"inference latency: p50={report.latency_p50_ms:.2f}ms "
        f"p95={report.latency_p95_ms:.2f}ms"
    )
    fast_complete_count = sum(
        prediction.source.startswith("fast_complete:")
        for prediction in report.predictions
    )
    if args.runtime:
        fast_predictions = [
            prediction
            for prediction in report.predictions
            if prediction.source.startswith("fast_complete:")
        ]
        fast_complete_precision = (
            sum(prediction.correct for prediction in fast_predictions)
            / len(fast_predictions)
            if fast_predictions
            else 0.0
        )
        provider_error_count = sum(
            prediction.source.startswith("evaluation_error:")
            for prediction in report.predictions
        )
        print(
            f"routing: fast-complete={fast_complete_count} "
            f"fallback={report.total - fast_complete_count} "
            f"provider-errors={provider_error_count} "
            f"fast-precision={_percentage(fast_complete_precision)}"
        )
    print(
        "\ncategory                         accuracy  complete-precision  "
        "false-cutoff  missed-endpoint"
    )
    for category, metrics in report.by_category.items():
        print(
            f"{category:<32} {_percentage(metrics.accuracy):>8} "
            f"{_percentage(metrics.complete_precision):>19} "
            f"{_percentage(metrics.false_cutoff_rate):>13} "
            f"{_percentage(metrics.missed_endpoint_rate):>16}"
        )
    failures = [item for item in report.predictions if not item.correct]
    print(f"\nerrors: {len(failures)}")
    for prediction in failures[:20]:
        probability = (
            f"{prediction.probability:.4f}"
            if prediction.probability is not None
            else "n/a"
        )
        print(
            f"- {prediction.case_id}: expected={prediction.expected.value} "
            f"predicted={prediction.predicted.value} p_eot={probability}"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                _report_payload(report, threshold=args.threshold),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
