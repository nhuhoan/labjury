import json

import pytest

from labjury.audit import (
    AuditEvent,
    ProvenanceRef,
    answer_from_dict,
    answer_to_dict,
    candidate_from_dict,
    candidate_to_dict,
    replay_decision,
    verdict_matches,
)
from labjury.policies import RecallBiasedPolicy
from labjury.decisions import Answer, Candidate, ChoiceQuestion, NoulQuestion
from labjury.defaults import InMemoryAuditLog, NullAuditLog
from labjury.plugins import AuditLog
from labjury.results import Action, Verdict
from labjury.testing import assert_audit_log_contract


class _FixedPolicy:
    """A policy that always returns a fixed verdict; carries an optional version."""

    def __init__(self, verdict, *, version=None):
        self._verdict = verdict
        if version is not None:
            self.version = version

    async def decide(self, state, candidates, answers, taxonomy):
        return self._verdict


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


async def test_inmemory_audit_log_satisfies_contract():
    await assert_audit_log_contract(InMemoryAuditLog)


async def test_null_audit_log_is_protocol_but_retains_nothing():
    log = NullAuditLog()
    assert isinstance(log, AuditLog)
    await log.record(AuditEvent("i1", "fp1"))
    assert await log.by_correlation("i1") == []


def test_audit_log_protocol_is_append_only():
    assert not hasattr(AuditLog, "update") and not hasattr(AuditLog, "delete")


def test_audit_logs_is_a_registry_kind():
    from labjury.registry import _KINDS
    assert "audit_logs" in _KINDS


def _decided_event(known):  # a decided event over a 'food' tag candidate
    c = Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))
    a = Answer("food_q", value="food", confidence=0.95)
    return AuditEvent(
        "i1", "fp1", used_proposer=True,
        candidates=(candidate_to_dict(c),), answers=(answer_to_dict(a),),
        known_labels=known,
        verdict={"action": "accept", "labels": ["food"], "scores": {"food": 0.95},
                 "novel_labels": [], "reason": "accepted"},
    )


async def test_replay_reproduces_recorded_verdict():
    event = _decided_event(known=frozenset({"food"}))  # food already official
    verdict = await replay_decision(event, RecallBiasedPolicy())
    assert verdict_matches(event, verdict)


async def test_replay_uses_snapshot_for_novelty():
    event = _decided_event(known=frozenset())  # empty snapshot -> food is novel
    verdict = await replay_decision(event, RecallBiasedPolicy())
    assert "food" in verdict.novel_labels


async def test_replay_of_cache_hit_raises():
    event = AuditEvent("i1", "fp1", from_cache=True, verdict={"action": "accept",
        "labels": [], "scores": {}, "novel_labels": [], "reason": "cached"})
    with pytest.raises(ValueError):
        await replay_decision(event, RecallBiasedPolicy())


def test_candidate_carries_rubric_version_through_audit_seam():
    c = Candidate("violence", "violation", NoulQuestion("violence", "?"), rubric_version="v2")
    d = candidate_to_dict(c)
    assert d["rubric_version"] == "v2"
    assert candidate_from_dict(d) == c


def test_candidate_without_rubric_version_roundtrips():
    c = Candidate("food", "tag", NoulQuestion("food", "?"))
    d = candidate_to_dict(c)
    assert d["rubric_version"] is None
    assert candidate_from_dict(d).rubric_version is None


def test_verdict_to_dict_shape():
    from labjury.audit import verdict_to_dict
    from labjury.results import Action, Verdict
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    assert verdict_to_dict(v) == {
        "action": "accept", "labels": ["a"], "scores": {"a": 0.9},
        "novel_labels": [], "reason": "ok",
    }


def test_provenance_of_reads_name_version_params():
    from labjury.audit import provenance_of
    class P:
        version = "1.2"
        params = {"k": 1}
    ref = provenance_of(P())
    assert (ref.name, ref.version, ref.params) == ("P", "1.2", {"k": 1})


def test_provenance_of_defaults_when_missing():
    from labjury.audit import provenance_of
    class Bare: ...
    ref = provenance_of(Bare())
    assert (ref.name, ref.version, ref.params) == ("Bare", None, None)


async def test_faithful_when_version_and_verdict_match():
    from labjury.audit import provenance_of, verdict_to_dict, verify_replay
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    policy = _FixedPolicy(v, version="1.0")
    event = AuditEvent("i1", "fp", provenance={"policy": provenance_of(policy)},
                       verdict=verdict_to_dict(v))
    report = await verify_replay(event, _FixedPolicy(v, version="1.0"))
    assert report.verdict_matches is True
    assert report.drift == {}
    assert report.faithful is True


async def test_version_drift_detected_even_when_verdict_matches():
    from labjury.audit import provenance_of, verdict_to_dict, verify_replay
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    event = AuditEvent("i1", "fp",
                       provenance={"policy": provenance_of(_FixedPolicy(v, version="1.0"))},
                       verdict=verdict_to_dict(v))
    report = await verify_replay(event, _FixedPolicy(v, version="2.0"))
    assert report.verdict_matches is True
    assert "policy" in report.drift
    assert report.drift["policy"].recorded.endswith("@1.0")
    assert report.drift["policy"].current.endswith("@2.0")
    assert report.faithful is False


async def test_verdict_mismatch_reported():
    from labjury.audit import provenance_of, verdict_to_dict, verify_replay
    recorded_v = Verdict(Action.ACCEPT, ["a"], {}, [], "ok")
    other_v = Verdict(Action.BLOCK, [], {}, [], "no")
    event = AuditEvent("i1", "fp",
                       provenance={"policy": provenance_of(_FixedPolicy(recorded_v, version="1.0"))},
                       verdict=verdict_to_dict(recorded_v))
    report = await verify_replay(event, _FixedPolicy(other_v, version="1.0"))
    assert report.verdict_matches is False
    assert report.faithful is False
    assert report.recorded_verdict["action"] == "accept"
    assert report.replayed_verdict["action"] == "block"


async def test_verify_replay_of_cache_hit_raises():
    from labjury.audit import verdict_to_dict, verify_replay
    v = Verdict(Action.ACCEPT, [], {}, [], "cached")
    event = AuditEvent("i1", "fp", from_cache=True, verdict=verdict_to_dict(v))
    with pytest.raises(ValueError):
        await verify_replay(event, _FixedPolicy(v))
