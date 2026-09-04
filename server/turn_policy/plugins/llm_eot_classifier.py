"""LLM-only semantic-completeness classifier.

The adapter owns prompt and response parsing.  Deadlines and operational
fallback are intentionally handled by ``SemanticEndpointGate`` so every LLM
provider receives the same liveness policy.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from server.brain.llm_clients import ChatMessage, LlmClient
from server.turn_policy.eot_classifier import EotClassification, EotContext, EotDecision

DEFAULT_SYSTEM_PROMPT = """You judge whether the latest spoken transcript is a complete user turn.

The conversation may include committed user and assistant messages before the
final user message. Use that history only to resolve references and short
contextual answers; classify the latest transcript, not the earlier messages.

Classify only semantic completeness; silence is evaluated separately.
- complete: the user has expressed an actionable or answerable thought.
- incomplete: the utterance clearly depends on words the user is likely to add.
- uncertain: evidence is mixed; suggest a short wait before committing.

Do not confuse brevity with incompleteness. Short but self-contained social
utterances and contextual commands are complete. For example, "你好", "谢谢",
"换一个", "继续", and "再说一遍" are complete. Open grammatical or semantic
slots such as "我想订一张从北京到" are incomplete.

Return one JSON object only, with exactly these semantic fields:
{"status":"complete|incomplete|uncertain","confidence":0.0,"wait_ms":0}
confidence must be between 0 and 1. wait_ms must be non-negative. For an
incomplete or uncertain result, use wait_ms for a useful short continuation
window; use 0 only when the runtime should apply its conservative fallback.
Do not add markdown or explanatory text."""

EOT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["complete", "incomplete", "uncertain"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "wait_ms": {"type": "number", "minimum": 0},
    },
    "required": ["status", "confidence", "wait_ms"],
    "additionalProperties": False,
}


class LlmEotClassifier:
    """Provider-neutral classifier implemented on the existing LlmClient Seam."""

    def __init__(
        self,
        llm_client: LlmClient,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        source: str = "llm",
    ) -> None:
        if not source:
            raise ValueError("EOT classifier source must be non-empty")
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._source = source

    async def classify(
        self, *, text: str, generation: int
    ) -> EotClassification:
        return await self.classify_with_context(
            text=text,
            generation=generation,
            context=EotContext(),
        )

    async def classify_with_context(
        self,
        *,
        text: str,
        generation: int,
        context: EotContext,
    ) -> EotClassification:
        del generation  # cancellation/staleness is owned by the endpoint gate
        user_text = json.dumps(
            {"transcript": text},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        messages = (
            ChatMessage(role="system", content=self._system_prompt),
            *(
                ChatMessage(role=message.role, content=message.content)
                for message in context.history
            ),
            ChatMessage(role="user", content=user_text),
        )
        stream_messages = getattr(self._llm_client, "stream_messages", None)
        if stream_messages is not None:
            fragments: list[str] = []
            async for delta in stream_messages(messages=messages, max_tokens=64):
                fragments.append(delta)
                result = _try_parse_classification("".join(fragments))
                if result is not None:
                    return replace(result, source=self._source)
            return replace(
                _parse_classification("".join(fragments)),
                source=self._source,
            )

        stream = getattr(self._llm_client, "stream", None)
        if stream is None:
            reply = await self._llm_client.complete(
                system_prompt=self._system_prompt,
                user_text=_fallback_user_text(context, user_text),
            )
            return replace(_parse_classification(reply), source=self._source)

        fragments: list[str] = []
        async for delta in stream(
            system_prompt=self._system_prompt,
            user_text=_fallback_user_text(context, user_text),
        ):
            fragments.append(delta)
            result = _try_parse_classification("".join(fragments))
            if result is not None:
                return replace(result, source=self._source)
        return replace(
            _parse_classification("".join(fragments)),
            source=self._source,
        )


def _fallback_user_text(context: EotContext, current_user_text: str) -> str:
    """Preserve semantics for legacy clients without structured messages.

    Production OpenAI-compatible clients take the structured path above so
    stable history remains a provider-cacheable prefix.
    """

    if not context.history:
        return current_user_text
    return json.dumps(
        {
            "history": [
                {"role": message.role, "content": message.content}
                for message in context.history
            ],
            "current": json.loads(current_user_text),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _try_parse_classification(reply: str) -> EotClassification | None:
    try:
        payload = json.loads(reply)
    except json.JSONDecodeError:
        return None
    return _classification_from_payload(payload)


def _parse_classification(reply: str) -> EotClassification:
    try:
        payload = json.loads(reply)
    except json.JSONDecodeError as exc:
        raise ValueError("semantic EOT reply must be valid JSON") from exc
    return _classification_from_payload(payload)


def _classification_from_payload(payload: Any) -> EotClassification:
    if not isinstance(payload, dict):
        raise TypeError("semantic EOT reply must be a JSON object")

    status = payload.get("status")
    if not isinstance(status, str):
        raise TypeError("semantic EOT status must be a string")
    try:
        decision = EotDecision(status.strip().lower())
    except ValueError as exc:
        raise ValueError(f"unsupported semantic EOT status: {status!r}") from exc

    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("semantic EOT confidence must be numeric")
    wait_ms = payload.get("wait_ms", 0)
    if isinstance(wait_ms, bool) or not isinstance(wait_ms, (int, float)):
        raise TypeError("semantic EOT wait_ms must be numeric")

    return EotClassification(
        decision=decision,
        confidence=float(confidence),
        wait_ms=float(wait_ms),
        source="llm",
    )
