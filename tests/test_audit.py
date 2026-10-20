import json

from labjury.audit import (
    AuditEvent,
    ProvenanceRef,
    answer_from_dict,
    answer_to_dict,
    candidate_from_dict,
    candidate_to_dict,
)
from labjury.decisions import Answer, Candidate, ChoiceQuestion, NoulQuestion


def test_full_event_round_trips_through_dict_and_json():
    c = Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))
    a = Answer("food_q", value="food", confidence=0.95)
    e = AuditEvent(
        "i1", "fp1",
        modalities=frozenset({"text"}),
        used_proposer=True,
        candidates=(candidate_to_dict(c),),
        answers=(answer_to_dict(a),),
        known_labels=frozenset({"food"}),
        provenance={"policy": ProvenanceRef("RecallBiasedPolicy", None, {"accept": 0.85})},
        verdict={"action": "accept", "labels": ["food"], "scores": {"food": 0.95},
                 "novel_labels": [], "reason": "accepted"},
    )
    assert AuditEvent.from_dict(e.to_dict()) == e
    assert AuditEvent.from_dict(json.loads(json.dumps(e.to_dict()))) == e


def test_cache_hit_event_round_trips():
    e = AuditEvent("i1", "fp1", from_cache=True,
                   verdict={"action": "accept", "labels": [], "scores": {},
                            "novel_labels": [], "reason": "cached"})
    assert AuditEvent.from_dict(e.to_dict()) == e


def test_candidate_and_answer_round_trip():
    c = Candidate("x", "violation", NoulQuestion("x", "bad?"))
    assert candidate_from_dict(candidate_to_dict(c)) == c
    a = Answer("x", value=False, confidence=0.9, distribution={"true": 0.1})
    assert answer_from_dict(answer_to_dict(a)) == a
