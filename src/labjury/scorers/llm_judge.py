"""The mandatory LLM-as-judge fallback scorer.

Keeps the framework runnable with no Jev access: any chat LLM can act as the
judge. The model SDK is *injected* as an async ``chat`` callable, so this
module imports no provider and stays testable with a fake. One call per
question (batching is a later optimization, not required here).
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from labjury.decisions import Answer, ChoiceQuestion, NoulQuestion, Question, ScoreQuestion
from labjury.state import State


def _render(question: Question) -> str:
    base = f"Question: {question.prompt}\n"
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
    accepts = frozenset({"*"})

    def __init__(self, chat: Callable[[str], Awaitable[str]]) -> None:
        self._chat = chat

    async def score(self, state: State, questions: list[Question]) -> list[Answer]:
        answers: list[Answer] = []
        for q in questions:
            raw = await self._chat(_render(q))
            data = json.loads(raw)
            answers.append(
                Answer(
                    key=q.key,
                    value=data["value"],
                    confidence=data["confidence"],
                    distribution=data.get("distribution"),
                )
            )
        return answers
