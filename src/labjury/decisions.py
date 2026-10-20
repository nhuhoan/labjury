"""Typed decision primitives, mirroring Jev's question/answer model.

Questions are asked of a :class:`~labjury.state.State`; answers carry a
confidence in [0, 1]. A :class:`Candidate` pairs a proposed label with the
question to ask about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union


@dataclass
class ChoiceQuestion:
    """Pick one of up to 255 options."""

    key: str
    prompt: str
    options: list[str]

    def __post_init__(self) -> None:
        if not 1 <= len(self.options) <= 255:
            raise ValueError("ChoiceQuestion needs 1..255 options")


@dataclass
class ScoreQuestion:
    """Place the state on an ordered verbal scale of 2..10 levels."""

    key: str
    prompt: str
    levels: list[str]

    def __post_init__(self) -> None:
        if not 2 <= len(self.levels) <= 10:
            raise ValueError("ScoreQuestion needs 2..10 levels")


@dataclass
class NoulQuestion:
    """A yes/no question; the answer's value is a bool with a probability."""

    key: str
    prompt: str


Question = Union[ChoiceQuestion, ScoreQuestion, NoulQuestion]


@dataclass
class Answer:
    """A typed answer to one question."""

    key: str
    value: Any
    confidence: float
    distribution: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")


@dataclass
class Candidate:
    """A proposed label (``kind`` e.g. 'tag' / 'topic' / 'violation') and its question."""

    label: str
    kind: str
    question: Question
    # Links this candidate to the registered rubric revision it was built from,
    # for audit/reproducibility. ``None`` when the question was authored inline
    # (no rubric registry in play). See ``labjury.rubrics``.
    rubric_version: str | None = None
