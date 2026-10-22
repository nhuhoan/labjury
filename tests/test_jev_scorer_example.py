"""Tests for the reference ``examples/jev_scorer.py`` multimodal adapter.

The example is not packaged; ``examples`` is on the pytest path (pyproject). The
transport is a fake dict-in/dict-out async callable — no network, no httpx. The
Jev-specific focus here is the image path (assets, base64) that Quyet lacks;
the choice/score/noul calibrated mapping mirrors Quyet and is re-pinned.
"""

import base64

import pytest

from labjury import Content, Scorer, State
from labjury.cost import CostMeter
from labjury.decisions import ChoiceQuestion, NoulQuestion, ScoreQuestion

from jev_scorer import IMAGE_HEADER, JevMissingAnswer, JevScorer, httpx_transport


def _transport(response, captured=None):
    async def transport(body):
        if captured is not None:
            captured.append(body)
        return response
    return transport


def _text_state(text="Please refund the extra charge."):
    s = State()
    s.add(Content("text", text))
    return s


QUESTIONS = [
    ChoiceQuestion("intent", "What does the customer want?", ["refund", "cancel", "other"]),
    NoulQuestion("billing", "Is this message about billing?"),
    ScoreQuestion("urgency", "How urgent?", ["can wait", "this week", "today"]),
]

SAMPLE = {
    "model": "jev-latest",
    "answers": {
        "intent": {"type": "choice", "choice": "refund", "confidence": 0.7,
                   "probabilities": {"refund": 0.8, "cancel": 0.15, "other": 0.05}},
        "billing": {"type": "noul", "noul": 0.98},
        "urgency": {"type": "score", "score": 1.7, "confidence": 0.55,
                    "legend": {"0": "can wait", "1": "this week", "2": "today"},
                    "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}},
    },
    "usage": {"input_tokens": 120, "output_tokens": 12},
}


# --- text round-trip, request shape (state is a bare string, no assets) -------

async def test_text_round_trip_and_request_shape():
    captured = []
    answers = await JevScorer(_transport(SAMPLE, captured)).score(_text_state(), QUESTIONS)
    assert [a.key for a in answers] == ["intent", "billing", "urgency"]

    (body,) = captured
    assert body["model"] == "jev-latest"
    assert body["state"] == "Please refund the extra charge."   # bare string, not {"message": …}
    assert "assets" not in body                                  # no images -> no assets
    assert body["questions"]["intent"]["criteria"] == {"refund": None, "cancel": None, "other": None}
    assert body["questions"]["urgency"]["criteria"] == ["can wait", "this week", "today"]
    assert body["questions"]["billing"] == {"type": "noul", "instructions": "Is this message about billing?"}


# --- the multimodal path: images become base64 assets -------------------------

async def test_image_bytes_become_base64_asset():
    captured = []
    s = _text_state("What's in the photo?")
    s.add(Content("image", b"\x89PNG_rawbytes", meta={"mime": "image/png"}))
    resp = {"answers": {"billing": {"type": "noul", "noul": 0.1}}}
    await JevScorer(_transport(resp, captured)).score(s, [QUESTIONS[1]])

    (body,) = captured
    asset = body["assets"]["image_0"]
    assert asset["type"] == "image"
    assert asset["format"] == "png"                              # derived from mime
    assert asset["data_base64"] == base64.b64encode(b"\x89PNG_rawbytes").decode("ascii")


async def test_explicit_format_and_prencoded_base64_passthrough():
    captured = []
    s = State()
    s.add(Content("image", "QUxSRUFEWV9CNjQ=", meta={"format": "jpeg"}))  # already base64 str
    resp = {"answers": {"billing": {"type": "noul", "noul": 0.9}}}
    await JevScorer(_transport(resp, captured)).score(s, [QUESTIONS[1]])  # image-only, text empty
    asset = captured[0]["assets"]["image_0"]
    assert asset["format"] == "jpeg"
    assert asset["data_base64"] == "QUxSRUFEWV9CNjQ="             # passed through unchanged


async def test_multiple_images_indexed():
    captured = []
    s = _text_state("compare these")
    s.add(Content("image", b"one"))
    s.add(Content("image", b"two"))
    await JevScorer(_transport(SAMPLE, captured)).score(s, [QUESTIONS[0]])
    assert set(captured[0]["assets"]) == {"image_0", "image_1"}


async def test_accepts_declares_image():
    assert JevScorer(_transport(SAMPLE)).accepts == frozenset({"text", "image"})


# --- calibrated answer mapping (mirrors Quyet) --------------------------------

async def test_choice_maps_value_and_distribution():
    (a,) = await JevScorer(_transport(
        {"answers": {"intent": SAMPLE["answers"]["intent"]}})).score(_text_state(), [QUESTIONS[0]])
    assert a.value == "refund" and a.confidence == 0.7
    assert a.distribution == {"refund": 0.8, "cancel": 0.15, "other": 0.05}


async def test_score_is_argmax_not_continuous():
    # continuous score 1.7 rounds to level 2 ("today"), but the mass is on 2 here
    # anyway; flip it so argmax and round(score) disagree:
    resp = {"answers": {"urgency": {"type": "score", "score": 1.7, "confidence": 0.55,
            "legend": {"0": "can wait", "1": "this week", "2": "today"},
            "probabilities": {"0": 0.1, "1": 0.8, "2": 0.1}}}}
    (a,) = await JevScorer(_transport(resp)).score(_text_state(), [QUESTIONS[2]])
    assert a.value == "this week"                                # argmax, not round(1.7)->today
    assert a.distribution == {"can wait": 0.1, "this week": 0.8, "today": 0.1}


@pytest.mark.parametrize(("noul", "value", "conf"), [(0.98, True, 0.98), (0.1, False, 0.9)])
async def test_noul_threshold_and_derived_confidence(noul, value, conf):
    resp = {"answers": {"billing": {"type": "noul", "noul": noul}}}
    (a,) = await JevScorer(_transport(resp)).score(_text_state(), [QUESTIONS[1]])
    assert a.value is value and a.confidence == pytest.approx(conf)
    assert a.distribution == pytest.approx({"true": noul, "false": 1.0 - noul})


async def test_choice_value_not_in_options_raises():
    resp = {"answers": {"intent": {"choice": "bogus", "confidence": 0.9, "probabilities": {"bogus": 1.0}}}}
    with pytest.raises(ValueError):
        await JevScorer(_transport(resp)).score(_text_state(), [QUESTIONS[0]])


# --- fail-closed on a missing answer -----------------------------------------

async def test_missing_answer_raises_fail_closed():
    resp = {"answers": {"intent": SAMPLE["answers"]["intent"]}}  # billing, urgency absent
    with pytest.raises(JevMissingAnswer) as ei:
        await JevScorer(_transport(resp)).score(_text_state(), QUESTIONS)
    assert set(ei.value.keys) == {"billing", "urgency"}


# --- cost metering, protocol conformance, empty-state guard -------------------

async def test_cost_meter_records_once():
    meter = CostMeter()
    await JevScorer(_transport(SAMPLE), cost_meter=meter, tenant="acme").score(_text_state(), QUESTIONS)
    u = meter.for_tenant("acme")
    assert (u.tokens_in, u.tokens_out, u.calls) == (120, 12, 1)


def test_satisfies_scorer_protocol():
    assert isinstance(JevScorer(_transport(SAMPLE)), Scorer)


async def test_empty_state_raises():
    with pytest.raises(ValueError):
        await JevScorer(_transport(SAMPLE)).score(State(), QUESTIONS)


# --- the turnkey transport sets the image opt-in header only when needed ------

def test_httpx_transport_is_callable_factory():
    # Build it (lazy httpx import happens on call, not construction) — we only
    # assert it returns a coroutine function without hitting the network.
    t = httpx_transport("fake-key")
    assert callable(t)
    assert IMAGE_HEADER == "TypeSafe-Danger-Zone-Images"
