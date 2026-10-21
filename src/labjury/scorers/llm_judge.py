"""The mandatory LLM-as-judge fallback scorer.

Keeps the framework runnable with no Jev access: any chat LLM can act as the
judge. The model SDK is *injected* as an async ``chat`` callable, so this
module imports no provider and stays testable with a fake. One call per
question (batching is a later optimization, not required here).
"""

from __future__ import annotations

import json
import math
from typing import Awaitable, Callable

from labjury.decisions import Answer, ChoiceQuestion, NoulQuestion, Question, ScoreQuestion
from labjury.state import State


def _render(state: State, question: Question) -> str:
    content = [
        {"modality": modality, "payload": piece.payload, "meta": piece.meta}
        for modality in sorted(state.modalities())
        for piece in state.get(modality)
    ]
    base = (
        f"Content to judge: {json.dumps(content, ensure_ascii=False, default=str)}\n"
        f"Question: {question.prompt}\n"
    )
    if isinstance(question, NoulQuestion):
        base += "Answer JSON {\"value\": <true|false>, \"confidence\": <0..1>}."
    elif isinstance(question, ChoiceQuestion):
        base += (
            f"Choose one of {question.options}. "
            "Answer JSON {\"value\": <option>, \"confidence\": <0..1>}."
        )
    elif isinstance(question, ScoreQuestion):
        base += (
            f"Rate on levels {question.levels}. "
            "Answer JSON {\"value\": <level>, \"confidence\": <0..1>}."
        )
    return base


class LLMJudgeScorer:
    accepts = frozenset({"text", "json", "metadata"})

    def __init__(self, chat: Callable[[str], Awaitable[str]]) -> None:
        self._chat = chat

    async def score(self, state: State, questions: list[Question]) -> list[Answer]:
        answers: list[Answer] = []
        for q in questions:
            raw = await self._chat(_render(state, q))
            data = json.loads(raw)
            if not isinstance(data, dict) or "value" not in data or "confidence" not in data:
                raise ValueError(
                    f"invalid answer for question {q.key!r}: expected value and confidence"
                )
            value = data["value"]
            if isinstance(q, NoulQuestion):
                valid = type(value) is bool
            elif isinstance(q, ChoiceQuestion):
                valid = isinstance(value, str) and value in q.options
            elif isinstance(q, ScoreQuestion):
                valid = isinstance(value, str) and value in q.levels
            else:
                raise TypeError(f"unsupported question type: {type(q).__name__}")
            if not valid:
                raise ValueError(f"invalid value {value!r} for question {q.key!r}")
            confidence = data["confidence"]
            if (
                type(confidence) not in (int, float)
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError(f"invalid confidence for question {q.key!r}")
            answers.append(
                Answer(
                    key=q.key,
                    value=value,
                    confidence=confidence,
                    distribution=data.get("distribution"),
                )
            )
        return answers
