"""Tests for the reference ``examples/quyet_scorer.py`` adapter.

The example is not packaged; ``examples`` is on the pytest path (pyproject) so
these import it directly. The transport is a fake dict-in/dict-out async
callable — no network, no httpx. Every mapping rule the design doc pins
(``docs/superpowers/specs/2026-10-22-quyet-scorer-design.md``) has a test here.
"""

import pytest

from labjury import Content, Scorer, State
from labjury.cost import CostMeter
from labjury.decisions import ChoiceQuestion, NoulQuestion, ScoreQuestion

from quyet_scorer import QuyetPartialFailure, QuyetScorer


def _state(text="Please close my card, I lost it yesterday."):
    s = State()
    s.add(Content("text", text))
    return s


def _transport(response, captured=None):
    async def transport(body):
        if captured is not None:
            captured.append(body)
        return response
    return transport


# --- the canonical three-question round-trip (the marketplace sample) ---------

SAMPLE = {
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "cancel",
            "confidence": 0.9936,
            "probabilities": {"cancel": 0.9957, "limit": 0.00026, "other": 0.00399},
        },
        "mood": {
            "type": "score",
            "score": 0.2121,
            "confidence": 0.6999,
            "legend": {"0": "calm", "1": "annoyed", "2": "angry"},
            "probabilities": {"0": 0.7999, "1": 0.1879, "2": 0.0121},
        },
        "urgent": {"type": "noul", "noul": 0.7316},
    },
    "partial_failures": None,
    "usage": {"input_tokens": 203, "output_tokens": 0, "total_tokens": 203},
}

QUESTIONS = [
    ChoiceQuestion("intent", "What does the customer want?", ["cancel", "limit", "other"]),
    NoulQuestion("urgent", "The request is urgent."),
    ScoreQuestion("mood", "How upset is the customer?", ["calm", "annoyed", "angry"]),
]


async def test_multi_question_round_trip_aligned_to_input_order():
    captured = []
    scorer = QuyetScorer(_transport(SAMPLE, captured))
    answers = await scorer.score(_state(), QUESTIONS)

    # Returned list is aligned to the input questions order.
    assert [a.key for a in answers] == ["intent", "urgent", "mood"]

    # Request shape: state.message + a typed entry per question key.
    (body,) = captured
    assert body["model"] == "Quyet-1.0-Large"
    assert body["state"] == {"message": "Please close my card, I lost it yesterday."}
    assert body["questions"]["intent"] == {
        "type": "choice",
        "instructions": "What does the customer want?",
        "criteria": {"cancel": None, "limit": None, "other": None},
    }
    assert body["questions"]["mood"] == {
        "type": "score",
        "instructions": "How upset is the customer?",
        "criteria": ["calm", "annoyed", "angry"],
    }
    assert body["questions"]["urgent"] == {
        "type": "noul",
        "instructions": "The request is urgent.",
    }


# --- choice ------------------------------------------------------------------

async def test_choice_echoes_value_and_distribution():
    resp = {"answers": {"intent": SAMPLE["answers"]["intent"]}}
    (a,) = await QuyetScorer(_transport(resp)).score(_state(), [QUESTIONS[0]])
    assert a.value == "cancel"
    assert a.confidence == 0.9936
    assert a.distribution == {"cancel": 0.9957, "limit": 0.00026, "other": 0.00399}


async def test_choice_value_not_in_options_raises():
    resp = {"answers": {"intent": {"choice": "bogus", "confidence": 0.9,
                                    "probabilities": {"bogus": 1.0}}}}
    with pytest.raises(ValueError):
        await QuyetScorer(_transport(resp)).score(_state(), [QUESTIONS[0]])


# --- score: argmax of the distribution, re-keyed by level --------------------

async def test_score_value_is_argmax_not_continuous_score():
    # continuous ``score`` 0.21 would round toward level 0 anyway, so force a
    # case where argmax and a naive rounding of ``score`` disagree: ``score``
    # near 2.0 ("angry") but the probability mass sits on "annoyed".
    resp = {"answers": {"mood": {
        "type": "score", "score": 1.9, "confidence": 0.55,
        "legend": {"0": "calm", "1": "annoyed", "2": "angry"},
        "probabilities": {"0": 0.2, "1": 0.7, "2": 0.1},
    }}}
    (a,) = await QuyetScorer(_transport(resp)).score(_state(), [QUESTIONS[2]])
    assert a.value == "annoyed"               # argmax, not round(1.9) -> angry
    assert a.confidence == 0.55               # Quyet's own
    assert a.distribution == {"calm": 0.2, "annoyed": 0.7, "angry": 0.1}
    assert a.value in QUESTIONS[2].levels
    assert pytest.approx(sum(a.distribution.values())) == 1.0


async def test_score_value_not_in_levels_raises():
    resp = {"answers": {"mood": {
        "type": "score", "score": 0.0, "confidence": 0.5,
        "legend": {"0": "ecstatic"}, "probabilities": {"0": 1.0},
    }}}
    with pytest.raises(ValueError):
        await QuyetScorer(_transport(resp)).score(_state(), [QUESTIONS[2]])


# --- noul: threshold at 0.5, confidence = mass on the chosen side ------------

@pytest.mark.parametrize(
    ("noul", "value", "confidence"),
    [(0.73, True, 0.73), (0.20, False, 0.80), (0.50, True, 0.50)],
)
async def test_noul_threshold_and_derived_confidence(noul, value, confidence):
    resp = {"answers": {"urgent": {"type": "noul", "noul": noul}}}
    (a,) = await QuyetScorer(_transport(resp)).score(_state(), [QUESTIONS[1]])
    assert a.value is value
    assert a.confidence == pytest.approx(confidence)
    assert a.distribution == pytest.approx({"true": noul, "false": 1.0 - noul})
    assert pytest.approx(sum(a.distribution.values())) == 1.0


# --- partial failures: fail-closed -------------------------------------------

async def test_missing_answer_raises_partial_failure_with_keys():
    resp = {"answers": {"intent": SAMPLE["answers"]["intent"]},  # urgent, mood absent
            "partial_failures": ["urgent", "mood"]}
    with pytest.raises(QuyetPartialFailure) as ei:
        await QuyetScorer(_transport(resp)).score(_state(), QUESTIONS)
    assert set(ei.value.keys) == {"urgent", "mood"}


async def test_partial_failure_emits_no_fabricated_answer():
    resp = {"answers": {"intent": SAMPLE["answers"]["intent"]}}
    with pytest.raises(QuyetPartialFailure):
        await QuyetScorer(_transport(resp)).score(_state(), QUESTIONS)


# --- cost metering side channel ----------------------------------------------

async def test_cost_meter_records_once_per_call():
    meter = CostMeter()
    scorer = QuyetScorer(_transport(SAMPLE), cost_meter=meter, tenant="acme")
    await scorer.score(_state(), QUESTIONS)
    u = meter.for_tenant("acme")
    assert (u.tokens_in, u.tokens_out, u.calls) == (203, 0, 1)


async def test_no_meter_is_fine():
    scorer = QuyetScorer(_transport(SAMPLE))  # no meter
    answers = await scorer.score(_state(), QUESTIONS)
    assert len(answers) == 3


# --- protocol conformance and empty-state guard ------------------------------

def test_satisfies_scorer_protocol():
    assert isinstance(QuyetScorer(_transport(SAMPLE)), Scorer)
    assert QuyetScorer(_transport(SAMPLE)).accepts == frozenset({"text"})


async def test_empty_text_state_raises():
    with pytest.raises(ValueError):
        await QuyetScorer(_transport(SAMPLE)).score(State(), QUESTIONS)
