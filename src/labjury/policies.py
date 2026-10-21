"""The default, recall-biased decision policy.

Safety is an asymmetry: a missed violation is far worse than a held clean
item. So a violation question is cleared only when the scorer is *confidently
clean*; anything short of that is held for review. Accepted labels unknown to
the taxonomy are proposed (open-world), never silently kept or dropped.

The policy is budget-agnostic — thresholds are defaults the deployer tunes;
it bakes in no human-routing budget. It never emits ``Action.BLOCK``: the
conservative default holds uncertain/positive violations for review, leaving
auto-block to a deployer's own policy plugin.
"""

from __future__ import annotations

from labjury.decisions import Answer, Candidate, ChoiceQuestion, NoulQuestion, ScoreQuestion
from labjury.plugins import TaxonomyStore
from labjury.results import Action, Verdict
from labjury.state import State


class RecallBiasedPolicy:
    def __init__(self, accept_threshold: float = 0.85, clean_threshold: float = 0.9) -> None:
        self._accept = accept_threshold
        self._clean = clean_threshold

    @property
    def params(self) -> dict:
        """Thresholds, captured into the audit trail as decision provenance."""
        return {"accept_threshold": self._accept, "clean_threshold": self._clean}

    @staticmethod
    def _matches_label(candidate: Candidate, answer: Answer) -> bool:
        question = candidate.question
        if isinstance(question, NoulQuestion):
            return answer.value is True
        if isinstance(question, ChoiceQuestion):
            return candidate.label in question.options and answer.value == candidate.label
        if isinstance(question, ScoreQuestion):
            # Only the highest ordered level is a positive label signal.
            return answer.value == question.levels[-1]
        return False

    async def decide(
        self,
        state: State,
        candidates: list[Candidate],
        answers: list[Answer],
        taxonomy: TaxonomyStore,
    ) -> Verdict:
        if not candidates:
            return Verdict(Action.REVIEW, [], {}, [], "no candidates; routed to review")

        by_key = {a.key: a for a in answers}
        scores: dict[str, float] = {}

        # 1. Violations first: hold unless confidently clean.
        for c in candidates:
            if c.kind != "violation":
                continue
            a = by_key.get(c.question.key)
            confidently_clean = (
                a is not None and a.value is False and a.confidence >= self._clean
            )
            if not confidently_clean:
                return Verdict(
                    Action.REVIEW,
                    [],
                    scores,
                    [],
                    f"held for review: possible violation {c.label!r}",
                )

        # 2. Accept confident non-violation labels; flag novel ones.
        accepted: list[str] = []
        novel: list[str] = []
        non_violation = [c for c in candidates if c.kind != "violation"]
        for c in non_violation:
            a = by_key.get(c.question.key)
            if a is None:
                continue
            scores[c.label] = a.confidence
            if a.confidence >= self._accept and self._matches_label(c, a):
                accepted.append(c.label)
                if not await taxonomy.is_known(c.label):
                    await taxonomy.propose(c.label)
                    novel.append(c.label)

        # 3. Non-violation candidates existed but none were confident -> review.
        if non_violation and not accepted:
            return Verdict(
                Action.REVIEW,
                [],
                scores,
                novel,
                "no confident label; routed to review",
            )

        return Verdict(Action.ACCEPT, accepted, scores, novel, "accepted")
