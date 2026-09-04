"""FireRedChat turn-detector adapter for the EoT evidence seam."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Literal, Protocol

from server.turn_policy.eot_classifier import (
    EotDecision,
    EotEvidence,
    EotRequest,
)

_PUNCTUATION = re.compile(r"[，。？！,.?!]")


class EotProbabilityModel(Protocol):
    """Synchronous local inference hidden behind the async provider."""

    def predict(self, text: str) -> float: ...


class FireRedChatEotProvider:
    """Run local FireRedChat inference off the realtime event loop."""

    def __init__(
        self,
        model: EotProbabilityModel,
        *,
        threshold: float = 0.5,
        max_concurrency: int = 2,
    ) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("FireRedChat threshold must be between 0 and 1")
        if max_concurrency < 1:
            raise ValueError("FireRedChat max concurrency must be positive")
        self._model = model
        self._threshold = threshold
        self._capacity = asyncio.Semaphore(max_concurrency)

    async def evaluate(self, request: EotRequest) -> EotEvidence:
        text = _PUNCTUATION.sub("", request.text).strip()
        if not text:
            return EotEvidence(
                decision=EotDecision.UNCERTAIN,
                source="fireredchat",
                confidence=0.0,
            )
        started_at = time.perf_counter()
        async with self._capacity:
            probability = float(await asyncio.to_thread(self._model.predict, text))
        inference_ms = (time.perf_counter() - started_at) * 1000
        if not 0.0 <= probability <= 1.0:
            raise ValueError("FireRedChat probability must be between 0 and 1")
        complete = probability >= self._threshold
        return EotEvidence(
            decision=(EotDecision.COMPLETE if complete else EotDecision.INCOMPLETE),
            source="fireredchat",
            confidence=probability if complete else 1.0 - probability,
            inference_ms=inference_ms,
            probability=probability,
            threshold=self._threshold,
        )


class FireRedChatOnnxModel:
    """Load one shared quantized ONNX model and tokenizer from local assets."""

    def __init__(
        self,
        model_dir: str | Path,
        *,
        language: Literal["chinese", "multilingual"] = "chinese",
        intra_op_threads: int = 2,
    ) -> None:
        if language not in {"chinese", "multilingual"}:
            raise ValueError("FireRedChat language must be chinese or multilingual")
        if intra_op_threads < 1:
            raise ValueError("FireRedChat intra-op threads must be positive")
        root = Path(model_dir).expanduser().resolve()
        model_path = root / f"{language}_best_model_q8.onnx"
        tokenizer_path = root / "tokenizer"
        if not model_path.is_file():
            raise FileNotFoundError(f"FireRedChat model not found: {model_path}")
        if not tokenizer_path.is_dir():
            raise FileNotFoundError(f"FireRedChat tokenizer not found: {tokenizer_path}")

        try:
            import numpy as np
            import onnxruntime as ort
            from transformers import AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "FireRedChat dependencies are missing; install the 'firered' extra"
            ) from error

        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = intra_op_threads
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._np = np
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(tokenizer_path),
            local_files_only=True,
            truncation_side="left",
        )

    def predict(self, text: str) -> float:
        inputs = self._tokenizer(
            text,
            truncation=True,
            padding="max_length",
            add_special_tokens=False,
            return_tensors="np",
            max_length=128,
        )
        outputs = self._session.run(
            None,
            {
                "input_ids": inputs["input_ids"].astype("int64"),
                "attention_mask": inputs["attention_mask"].astype("int64"),
            },
        )
        logits = outputs[0]
        exponentials = self._np.exp(logits - self._np.max(logits, axis=1, keepdims=True))
        probabilities = exponentials / self._np.sum(exponentials, axis=1, keepdims=True)
        return float(probabilities.flatten()[-1])
