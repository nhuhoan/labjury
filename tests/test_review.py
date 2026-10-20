import pytest

from labjury.audit import AuditEvent
from labjury.results import Action
from labjury.review import ReviewResolution, ReviewTask, review_task_from_event


def test_review_task_from_event():
    event = AuditEvent(
        "c1",
        "fp",
        candidates=({"label": "x", "kind": "tag", "question": {}, "rubric_version": None},),
        answers=({"key": "x", "value": True, "confidence": 0.5, "distribution": None},),
        verdict={"action": "review", "labels": [], "scores": {}, "novel_labels": [], "reason": "unsure"},
        tenant="acme",
    )
    task = review_task_from_event(event)
    assert task.correlation_id == "c1"
    assert task.candidates[0]["label"] == "x"
    assert task.answers[0]["key"] == "x"
    assert task.tentative_verdict["action"] == "review"
    assert task.tenant == "acme"


def test_review_task_roundtrip():
    task = ReviewTask("c1", ({"label": "x"},), ({"key": "x"},), {"action": "review"}, "acme")
    assert ReviewTask.from_dict(task.to_dict()) == task


def test_resolution_roundtrip():
    r = ReviewResolution("c1", "block", ["nsfw"], "alice", "clear violation")
    assert ReviewResolution.from_dict(r.to_dict()) == r


def test_from_dict_tolerates_missing_optionals():
    task = ReviewTask.from_dict({"correlation_id": "c1"})
    assert task.candidates == () and task.tenant is None
    r = ReviewResolution.from_dict(
        {"correlation_id": "c1", "action": "accept", "labels": [], "reviewer": "bob"}
    )
    assert r.note == ""


def test_resolution_to_verdict():
    v = ReviewResolution("c1", "block", ["nsfw"], "alice", "bad").to_verdict()
    assert v.action is Action.BLOCK
    assert v.labels == ["nsfw"]
    assert v.scores == {}
    assert "bad" in v.reason


def test_resolution_unknown_action_raises():
    with pytest.raises(ValueError):
        ReviewResolution("c1", "frobnicate", [], "alice").to_verdict()
