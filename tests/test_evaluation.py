import pytest

from labjury.evaluation import (
    EvalReport,
    LabelScore,
    compare_evals,
    score_predictions,
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
