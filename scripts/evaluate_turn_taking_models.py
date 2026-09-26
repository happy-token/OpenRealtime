"""Compare text-level turn-taking judgments on a small curated dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from server.brain.plugins.openai_compatible_llm_client import OpenAiCompatibleLlmClient

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/eot_eval/turn_taking_v2.jsonl"
CHALLENGE_DATASET = ROOT / "data/eot_eval/turn_taking_challenge_v2.jsonl"
HOLDOUT_DATASET = ROOT / "data/eot_eval/turn_taking_prompt_holdout.jsonl"
LABELS = {
    "completeness": ("complete", "incomplete", "uncertain"),
    "interruption": ("backchannel", "stop", "correction", "interrupt", "ignore", "uncertain"),
}
DEFINITIONS = {
    "completeness": {
        "complete": "当前用户表达在上下文中已经形成可回应的完整意图，缺少执行参数不等于未说完",
        "incomplete": "当前表达的语法或意思明显悬空，仍依赖用户即将补充的话语",
        "uncertain": "有相互矛盾的证据，不能可靠判断用户是否说完，应该再等待",
    },
    "interruption": {
        "backchannel": "当前用户简短附和，鼓励助手继续说，不要求停播",
        "stop": "当前用户只要求助手停止播报，没有新的任务",
        "correction": "当前用户纠正助手正在回答所依赖的事实或自己的先前信息，需要停播",
        "interrupt": "当前用户提出新任务、补充要求或切换话题，需要停播并接管话轮",
        "ignore": "旁人讲话、背景音或与助手无关的声音，不应停播",
        "uncertain": "证据不足以可靠判断是否应该停播",
    },
}
INSTRUCTIONS = {
    "completeness": (
        "只判断最新累计语音转写是否语义完整；结合已提交的对话历史理解指代。"
        "不依赖标点、ASR 的结束标志、停顿或能否立即执行任务。"
        "完整、不完整和不确定是互斥选项。"
    ),
    "interruption": (
        "助手正在播报。根据正在播报的内容、当前语音转写及观察信息，判断现在是否应该停播。"
        "不要判断用户是否已经说完。区分用户的附和、单纯终止、纠正、新任务，以及背景人声/噪声。"
        "如果信息不足，请选 uncertain，不要假定背景语音是对助手说的。"
    ),
}
SOURCE_AWARE_INSTRUCTIONS = {
    "completeness": (
        "判断 `transcript` 当前这段累计用户表达是否已经形成可回应的完整意思，"
        "结合 `history` 解释省略和指代。若句尾的助词、介词、连词、动作或修饰语"
        "仍在等待其必需的对象或后续谓语，选 incomplete；即使前半句已经可理解，"
        "也不要替用户补完。若意图已表达清楚，仅缺下单日期等可追问的执行参数，"
        "选 complete。仅当转写证据本身不足或冲突时选 uncertain。"
        "不要把停顿、标点或 ASR 边界当作语义完结。"
    ),
    "interruption": (
        "助手正在播报。先根据 `observation` 判断 `transcript` 是否来自当前用户"
        "并指向助手，再结合 `assistant_playback` 判断动作；`boundary` 只表示 ASR"
        "边界，不证明说话者身份。若观察明确显示是电视、旁人对别的设备说话、"
        "扬声器回声或非语音噪声，选 ignore，即使转写看起来是停播命令、纠正或新任务。"
        "若没有这种排除证据，则根据当前用户话语选择：鼓励继续选 backchannel；"
        "只要求停止选 stop；纠正当前播报所依据的信息选 correction；"
        "提出需接管话轮的新任务或要求选 interrupt。不要把缺少声源观察本身当成"
        "背景声音；只有证据相互矛盾或无法判断时选 uncertain。"
    ),
}


def load_cases(path: Path, *, split: str = "baseline") -> list[dict]:
    cases = []
    ids = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        task = case["task"]
        valid_labels = (*LABELS[task], "review") if task == "completeness" else LABELS[task]
        if case["label"] not in valid_labels or case["id"] in ids:
            raise ValueError(f"invalid or duplicate label/id on line {number}")
        if not isinstance(case["transcript"], str) or not case["transcript"]:
            raise ValueError(f"empty transcript on line {number}")
        case["split"] = split
        ids.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("empty dataset")
    return cases


def state_for(case: dict) -> dict:
    if case["task"] == "completeness":
        return {"transcript": case["transcript"], "history": case["history"]}
    return {
        "assistant_playback": case["assistant_playback"],
        "transcript": case["transcript"],
        "boundary": case["boundary"],
        "observation": case.get("observation", ""),
    }


def read_key(path: Path, name: str) -> str:
    if value := os.environ.get(name):
        return value
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    raise ValueError(f"{name} is not configured in environment or {path}")


def latency_metrics(rows: list[dict]) -> dict:
    """Complete-request wall time, including unsuccessful responses."""

    if not rows:
        return {"mean_ms": None, "p90_ms": None, "p50_ms": None, "p95_ms": None}
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "mean_ms": round(fmean(latencies), 1),
        "p90_ms": latencies[math.ceil(0.9 * len(latencies)) - 1],
        "p50_ms": latencies[math.ceil(0.5 * len(latencies)) - 1],
        "p95_ms": latencies[math.ceil(0.95 * len(latencies)) - 1],
    }


def score(rows: list[dict]) -> dict:
    matrix: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        matrix[row["expected"]][row["predicted"] or "error"] += 1
    total = len(rows)
    determinate = [row for row in rows if row["expected"] != "review"]
    correct = sum(row["expected"] == row["predicted"] for row in determinate)
    labels = sorted({row["expected"] for row in determinate})
    per_label = {}
    for label in labels:
        tp = sum(row["expected"] == row["predicted"] == label for row in determinate)
        fp = sum(row["expected"] != label and row["predicted"] == label for row in determinate)
        fn = sum(row["expected"] == label and row["predicted"] != label for row in determinate)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_label[label] = {
            "support": tp + fn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
    return {
        "total": total,
        "evaluated": len(determinate),
        "accuracy": correct / len(determinate) if determinate else None,
        "macro_precision": fmean(item["precision"] for item in per_label.values())
        if per_label
        else None,
        "macro_recall": fmean(item["recall"] for item in per_label.values()) if per_label else None,
        "macro_f1": fmean(item["f1"] for item in per_label.values()) if per_label else None,
        "per_label": per_label,
        "review_uncertain_rate": (
            sum(row["predicted"] == "uncertain" for row in rows if row["expected"] == "review")
            / (total - len(determinate))
            if total != len(determinate)
            else None
        ),
        "determinate_abstention_rate": (
            sum(row["predicted"] == "uncertain" for row in determinate) / len(determinate)
            if determinate
            else None
        ),
        "errors": sum(row["predicted"] is None for row in rows),
        "by_expected": {label: dict(counts) for label, counts in sorted(matrix.items())},
        "latency": latency_metrics(rows),
    }


async def run_typesafe(
    cases: list[dict], key: str, *, instructions: dict[str, str] = INSTRUCTIONS
) -> list[dict]:
    from typesafe_sdk import Choice, TypeSafeClient  # type: ignore[import-not-found]

    rows = []
    with TypeSafeClient(api_key=key, timeout=20) as client:
        for case in cases:
            task = case["task"]
            started = time.perf_counter()
            predicted = None
            confidence = None
            error = None
            try:
                response = await asyncio.to_thread(
                    client.system_one,
                    state=state_for(case),
                    questions={
                        task: Choice(
                            instructions=instructions[task],
                            criteria=DEFINITIONS[task],
                        )
                    },
                )
                answer = response.choices[task]
                predicted, confidence = answer.choice, answer.confidence
                if predicted not in LABELS[task]:
                    raise ValueError("unknown TypeSafe label")
            except Exception as exc:  # noqa: BLE001 - retain provider failures per case
                predicted, confidence, error = None, None, type(exc).__name__
            rows.append(_row(case, predicted, confidence, started, error))
    return rows


async def run_deepseek(cases: list[dict], *, key: str) -> list[dict]:
    clients = {
        task: OpenAiCompatibleLlmClient(
            api_key=key,
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            disable_thinking=True,
            api_style="responses",
            response_schema={
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": list(LABELS[task])},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["label", "confidence"],
                "additionalProperties": False,
            },
            response_schema_name=f"turn_taking_{task}",
            timeout_s=30,
        )
        for task in LABELS
    }
    rows = []
    for case in cases:
        task = case["task"]
        started = time.perf_counter()
        predicted = None
        confidence = None
        error = None
        try:
            prompt = (
                INSTRUCTIONS[task] + "\n只返回 JSON 对象，字段 label 是下列一个选项，"
                "confidence 是 0 到 1 的数字。\n"
                + json.dumps(DEFINITIONS[task], ensure_ascii=False)
            )
            raw = await clients[task].complete(
                system_prompt=prompt,
                user_text=json.dumps(state_for(case), ensure_ascii=False),
            )
            answer = json.loads(raw)
            predicted = answer["label"]
            confidence = answer.get("confidence")
            if predicted not in LABELS[task] or not isinstance(confidence, (int, float)):
                raise ValueError("invalid LLM label or confidence")
            if isinstance(confidence, bool) or not 0 <= confidence <= 1:
                raise ValueError("invalid LLM confidence")
        except Exception as exc:  # noqa: BLE001 - retain provider failures per case
            predicted, confidence, error = None, None, type(exc).__name__
        rows.append(_row(case, predicted, confidence, started, error))
    return rows


def _row(
    case: dict, predicted: str | None, confidence: float | None, started: float, error: str | None
) -> dict:
    return {
        "id": case["id"],
        "split": case["split"],
        "task": case["task"],
        "category": case["category"],
        "expected": case["label"],
        "predicted": predicted,
        "confidence": confidence,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "error": error,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        action="append",
        help="repeat to combine datasets; defaults to baseline and challenge",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/turn-taking-v2.json")
    parser.add_argument("--repeats", type=int, default=5, help="calls per case and provider")
    parser.add_argument(
        "--typesafe-prompt",
        choices=("baseline", "source-aware"),
        default="baseline",
        help="TypeSafe question wording; baseline preserves the previous evaluation",
    )
    parser.add_argument(
        "--provider", choices=("typesafe", "deepseek"), action="append",
        help="repeat to select providers; defaults to both",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    datasets = args.dataset or [DATASET, CHALLENGE_DATASET]
    cases = [
        case
        for path in datasets
        for case in load_cases(
            path,
            split=(
                "challenge"
                if path.resolve() == CHALLENGE_DATASET
                else "holdout" if path.resolve() == HOLDOUT_DATASET else "baseline"
            ),
        )
    ]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("case ids must be unique across datasets")
    key_paths = {
        "typesafe": (ROOT.parent / "open/.env", "JEV_API_KEY"),
        "deepseek": (ROOT / ".env", "DEEPSEEK_API_KEY"),
    }
    keys = {
        provider: read_key(*key_paths[provider])
        for provider in (args.provider or list(key_paths))
    }
    instructions = (
        INSTRUCTIONS if args.typesafe_prompt == "baseline" else SOURCE_AWARE_INSTRUCTIONS
    )
    runs: dict[str, list[list[dict]]] = {provider: [] for provider in keys}
    for repeat in range(1, args.repeats + 1):
        for provider, key in keys.items():
            rows = (
                await run_typesafe(cases, key, instructions=instructions)
                if provider == "typesafe"
                else await run_deepseek(cases, key=key)
            )
            for row in rows:
                row["repeat"] = repeat
            runs[provider].append(rows)
            print(f"round {repeat}/{args.repeats}: {provider} ({len(rows)} cases)", flush=True)

    output: dict[str, Any] = {
        "datasets": [str(path) for path in datasets],
        "repeats": args.repeats,
        "typesafe_prompt": args.typesafe_prompt,
        "latency_definition": "full request wall time including response parsing and failed requests",
        "percentile_method": "nearest rank",
        "models": {},
    }
    for provider, provider_runs in runs.items():
        rows = [row for round_rows in provider_runs for row in round_rows]
        output["models"][provider] = {
            "model": "jev-1.13.0 (SDK default observed in smoke test)"
            if provider == "typesafe"
            else "deepseek-v4-flash",
            "tasks": {task: score([row for row in rows if row["task"] == task]) for task in LABELS},
            "splits": {
                split: {
                    task: score(
                        [row for row in rows if row["split"] == split and row["task"] == task]
                    )
                    for task in LABELS
                }
                for split in sorted({row["split"] for row in rows})
            },
            "latency": latency_metrics(rows),
            "rounds": [
                {
                    "repeat": index,
                    "latency": latency_metrics(round_rows),
                    "tasks": {
                        task: score([row for row in round_rows if row["task"] == task])
                        for task in LABELS
                    },
                }
                for index, round_rows in enumerate(provider_runs, 1)
            ],
            "predictions": rows,
        }
        print(
            provider,
            {task: output["models"][provider]["tasks"][task]["accuracy"] for task in LABELS},
            output["models"][provider]["latency"],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    asyncio.run(main())
