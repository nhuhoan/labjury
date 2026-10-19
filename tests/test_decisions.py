import pytest

from labjury import (
    Answer,
    Candidate,
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
)


def test_choice_rejects_over_255_options():
    with pytest.raises(ValueError):
        ChoiceQuestion("topic", "which topic?", [f"o{i}" for i in range(256)])


def test_choice_accepts_up_to_255_options():
    q = ChoiceQuestion("topic", "which topic?", [f"o{i}" for i in range(255)])
    assert len(q.options) == 255


def test_score_requires_2_to_10_levels():
    ScoreQuestion("quality", "how good?", ["low", "high"])  # ok
    with pytest.raises(ValueError):
        ScoreQuestion("quality", "how good?", ["only_one"])
    with pytest.raises(ValueError):
        ScoreQuestion("quality", "how good?", [f"l{i}" for i in range(11)])


def test_noul_question_constructs():
    assert NoulQuestion("is_violation", "violates policy?").key == "is_violation"


def test_answer_confidence_bounds():
    Answer("is_violation", value=False, confidence=0.9)  # ok
    with pytest.raises(ValueError):
        Answer("is_violation", value=False, confidence=1.5)
    with pytest.raises(ValueError):
        Answer("is_violation", value=False, confidence=-0.1)


def test_candidate_wraps_question():
    c = Candidate("alcohol", "violation", NoulQuestion("alcohol", "promotes alcohol?"))
    assert c.kind == "violation" and c.question.key == "alcohol"
