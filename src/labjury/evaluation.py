"""Evaluation harness — golden sets, precision/recall/F1, policy regression.

LabJury owns the measurement *mechanism*, not the data or the gate: it does not ship
golden datasets (those are the deployer's labeled data) and it does not integrate
with any CI system (the deployer calls these functions from their own pipeline). The
math is pure, deterministic, and zero-dependency.

Metrics are over the pipeline's verdict **labels** — the decision that actually
ships. :func:`score_predictions` is the pure core; :func:`run_evaluation` runs a
golden set through an engine; :func:`compare_evals` diffs two runs for regression
gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from labjury.results import Action
from labjury.state import Item


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


@dataclass(frozen=True)
class LabelScore:
    """Per-label confusion counts and the metrics derived from them."""

    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


@dataclass(frozen=True)
class EvalReport:
    """Label-set metrics for one evaluation run."""

    n_cases: int
    exact_matches: int
    per_label: dict[str, LabelScore]

    @property
    def micro_precision(self) -> float:
        tp = sum(s.tp for s in self.per_label.values())
        fp = sum(s.fp for s in self.per_label.values())
        return _ratio(tp, tp + fp)

    @property
    def micro_recall(self) -> float:
        tp = sum(s.tp for s in self.per_label.values())
        fn = sum(s.fn for s in self.per_label.values())
        return _ratio(tp, tp + fn)

    @property
    def micro_f1(self) -> float:
        p, r = self.micro_precision, self.micro_recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0

    def _macro(self, attr: str) -> float:
        if not self.per_label:
            return 0.0
        return sum(getattr(s, attr) for s in self.per_label.values()) / len(self.per_label)

    @property
    def macro_precision(self) -> float:
        return self._macro("precision")

    @property
    def macro_recall(self) -> float:
        return self._macro("recall")

    @property
    def macro_f1(self) -> float:
        return self._macro("f1")

    @property
    def exact_match_rate(self) -> float:
        return _ratio(self.exact_matches, self.n_cases)


def score_predictions(
    pairs: Iterable[tuple[set[str], set[str]]],
) -> EvalReport:
    """Score ``(expected_labels, predicted_labels)`` pairs into an :class:`EvalReport`."""
    counts: dict[str, list[int]] = {}  # label -> [tp, fp, fn]
    n_cases = 0
    exact_matches = 0
    for expected, predicted in pairs:
        n_cases += 1
        expected, predicted = set(expected), set(predicted)
        if expected == predicted:
            exact_matches += 1
        for label in expected | predicted:
            tp, fp, fn = counts.setdefault(label, [0, 0, 0])
            if label in expected and label in predicted:
                counts[label][0] = tp + 1
            elif label in predicted:
                counts[label][1] = fp + 1
            else:
                counts[label][2] = fn + 1
    per_label = {
        label: LabelScore(label, tp, fp, fn) for label, (tp, fp, fn) in counts.items()
    }
    return EvalReport(n_cases, exact_matches, per_label)


@dataclass(frozen=True)
class ActionReport:
    """Action-level metrics: the shipped decision (ACCEPT/BLOCK/REVIEW) scored as a
    3-class problem. ``confusion`` is keyed by ``(expected_action, predicted_action)``
    action-value strings (predicted ``"none"`` = the pipeline produced no action);
    ``per_action`` is one-vs-rest per real action, reusing :class:`LabelScore`."""

    n_cases: int
    confusion: dict[tuple[str, str], int]
    per_action: dict[str, LabelScore]

    @property
    def accuracy(self) -> float:
        correct = sum(n for (e, p), n in self.confusion.items() if e == p)
        return _ratio(correct, self.n_cases)


def score_actions(
    pairs: Iterable[tuple[Action, Action | None]],
) -> ActionReport:
    """Score ``(expected_action, predicted_action)`` pairs into an :class:`ActionReport`.

    ``predicted is None`` means the pipeline produced no action (a ``FAILED`` item);
    it is bucketed under the predicted key ``"none"``, counts as a false negative for
    the expected action, and is never a true positive. ``per_action`` metrics are
    one-vs-rest over the real action classes that appear as an expected value."""
    confusion: dict[tuple[str, str], int] = {}
    n_cases = 0
    for expected, predicted in pairs:
        n_cases += 1
        key = (expected.value, predicted.value if predicted is not None else "none")
        confusion[key] = confusion.get(key, 0) + 1
    real_actions = {e for (e, _p) in confusion}
    per_action = {
        a: LabelScore(
            a,
            confusion.get((a, a), 0),
            sum(n for (e, p), n in confusion.items() if p == a and e != a),
            sum(n for (e, p), n in confusion.items() if e == a and p != a),
        )
        for a in real_actions
    }
    return ActionReport(n_cases, confusion, per_action)


@dataclass(frozen=True)
class GoldenCase:
    """A ground-truth example: an item and the labels a correct pipeline should emit."""

    item: Item
    expected_labels: frozenset[str]


async def run_evaluation(engine, cases: Iterable[GoldenCase]) -> EvalReport:
    """Run a golden set through ``engine`` and score the verdict labels.

    A result with no verdict (e.g. a ``FAILED`` item) is scored as an empty
    prediction — a pipeline that fails to decide earns no credit."""
    pairs: list[tuple[set[str], set[str]]] = []
    for case in cases:
        result = await engine.process(case.item)
        predicted = set(result.verdict.labels) if result.verdict else set()
        pairs.append((set(case.expected_labels), predicted))
    return score_predictions(pairs)


@dataclass(frozen=True)
class EvalComparison:
    """A baseline-vs-candidate diff for policy-regression gating."""

    baseline: EvalReport
    candidate: EvalReport
    micro_f1_delta: float
    macro_f1_delta: float
    regressed_labels: list[str]

    def regressed(self, tolerance: float = 0.0) -> bool:
        """True if the candidate's micro-F1 dropped by more than ``tolerance``."""
        return self.micro_f1_delta < -tolerance


def compare_evals(baseline: EvalReport, candidate: EvalReport) -> EvalComparison:
    """Diff two reports: micro/macro F1 deltas and the labels whose F1 fell."""
    regressed = [
        label
        for label, base in baseline.per_label.items()
        if label in candidate.per_label and candidate.per_label[label].f1 < base.f1
    ]
    return EvalComparison(
        baseline,
        candidate,
        candidate.micro_f1 - baseline.micro_f1,
        candidate.macro_f1 - baseline.macro_f1,
        regressed,
    )
