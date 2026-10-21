import pytest

from labjury.evaluation import (
    EvalReport,
    GoldenCase,
    LabelScore,
    compare_evals,
    run_evaluation,
    score_predictions,
)
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.state import Item


class _FakeEngine:
    """Returns a verdict with chosen labels per item id; id mapped to None -> FAILED."""

    def __init__(self, labels_by_id):
        self._labels = labels_by_id

    async def process(self, item):
        labels = self._labels.get(item.id)
        if labels is None:
            return ItemResult(item.id, Status.FAILED, error="boom")
        return ItemResult(
            item.id,
            Status.DECIDED,
            verdict=Verdict(Action.BLOCK, list(labels), {}, [], "x"),
        )


def test_worked_example():
    # Case A: expected {spam,nsfw} predicted {spam}; Case B: expected {spam} predicted {spam,ads}
    report = score_predictions([
        ({"spam", "nsfw"}, {"spam"}),
        ({"spam"}, {"spam", "ads"}),
    ])
    assert report.n_cases == 2
    assert report.per_label["spam"].f1 == 1.0
    assert report.micro_precision == pytest.approx(2 / 3)
    assert report.micro_recall == pytest.approx(2 / 3)
    assert report.micro_f1 == pytest.approx(2 / 3)
    assert report.macro_f1 == pytest.approx(1 / 3)
    assert report.exact_match_rate == 0.0


def test_exact_match_counts():
    report = score_predictions([({"a"}, {"a"}), ({"a"}, {"b"})])
    assert report.exact_matches == 1
    assert report.exact_match_rate == 0.5


def test_empty_report():
    report = score_predictions([])
    assert report.n_cases == 0
    assert report.micro_f1 == 0.0 and report.macro_f1 == 0.0
    assert report.exact_match_rate == 0.0


def test_zero_denominators():
    report = score_predictions([(set(), {"ghost"})])   # only a false positive
    assert report.per_label["ghost"].precision == 0.0
    assert report.per_label["ghost"].recall == 0.0
    assert report.per_label["ghost"].f1 == 0.0


def test_regression_detected():
    base = score_predictions([({"a"}, {"a"}), ({"b"}, {"b"})])          # perfect
    cand = score_predictions([({"a"}, {"a"}), ({"b"}, set())])          # b now missed
    cmp = compare_evals(base, cand)
    assert cmp.micro_f1_delta < 0
    assert cmp.regressed() is True
    assert "b" in cmp.regressed_labels


def test_improvement_not_regression():
    base = score_predictions([({"a"}, set())])
    cand = score_predictions([({"a"}, {"a"})])
    assert compare_evals(base, cand).regressed() is False


def test_tolerance():
    base = score_predictions([({"a"}, {"a"}), ({"a"}, {"a"})])
    cand = score_predictions([({"a"}, {"a"}), ({"a"}, set())])   # micro_f1 drops
    cmp = compare_evals(base, cand)
    assert cmp.regressed(tolerance=0.0) is True
    assert cmp.regressed(tolerance=1.0) is False


async def test_run_evaluation_matches_score_predictions():
    engine = _FakeEngine({"i1": {"spam"}, "i2": {"spam", "ads"}})
    cases = [
        GoldenCase(Item("i1", {}), frozenset({"spam", "nsfw"})),
        GoldenCase(Item("i2", {}), frozenset({"spam"})),
    ]
    report = await run_evaluation(engine, cases)
    expected = score_predictions([
        ({"spam", "nsfw"}, {"spam"}),
        ({"spam"}, {"spam", "ads"}),
    ])
    assert report.per_label.keys() == expected.per_label.keys()
    assert report.micro_f1 == expected.micro_f1
    assert report.n_cases == 2


async def test_failed_result_is_empty_prediction():
    engine = _FakeEngine({"i1": None})     # FAILED -> no verdict
    report = await run_evaluation(engine, [GoldenCase(Item("i1", {}), frozenset({"spam"}))])
    assert report.per_label["spam"].fn == 1
    assert report.per_label["spam"].recall == 0.0


# -- action-level evaluation ---------------------------------------------------


def test_all_correct():
    from labjury.evaluation import score_actions
    from labjury.results import Action

    r = score_actions([(Action.BLOCK, Action.BLOCK), (Action.ACCEPT, Action.ACCEPT)])
    assert r.accuracy == 1.0
    assert r.per_action["block"].f1 == 1.0
    assert r.per_action["accept"].f1 == 1.0


def test_misroute():
    from labjury.evaluation import score_actions
    from labjury.results import Action

    # expected BLOCK but predicted REVIEW
    r = score_actions([(Action.BLOCK, Action.REVIEW)])
    assert r.confusion[("block", "review")] == 1
    assert r.accuracy == 0.0
    assert r.per_action["block"].recall == 0.0  # the BLOCK was missed
    assert r.per_action["block"].fn == 1


def test_none_predicted_is_failure():
    from labjury.evaluation import score_actions
    from labjury.results import Action

    r = score_actions([(Action.BLOCK, None)])
    assert r.confusion[("block", "none")] == 1
    assert r.per_action["block"].fn == 1
    assert r.per_action["block"].tp == 0
    assert "none" not in r.per_action  # "none" is not a real class


def test_empty():
    from labjury.evaluation import score_actions

    r = score_actions([])
    assert r.accuracy == 0.0 and r.per_action == {}
