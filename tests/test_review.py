import pytest

from labjury.audit import AuditEvent
from labjury.plugins import ReviewQueue
from labjury.results import Action
from labjury.review import (
    InMemoryReviewQueue,
    ReviewResolution,
    ReviewTask,
    review_task_from_event,
)


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


async def test_enqueue_and_drain():
    q = InMemoryReviewQueue()
    assert await q.enqueue(ReviewTask("c1")) is None
    await q.enqueue(ReviewTask("c2"))
    assert [t.correlation_id for t in q.pending()] == ["c1", "c2"]
    drained = q.drain()
    assert [t.correlation_id for t in drained] == ["c1", "c2"]
    assert q.pending() == []


async def test_pending_is_a_copy():
    q = InMemoryReviewQueue()
    await q.enqueue(ReviewTask("c1"))
    q.pending().clear()
    assert len(q.pending()) == 1


def test_in_memory_queue_is_a_review_queue():
    assert isinstance(InMemoryReviewQueue(), ReviewQueue)


# -- override_event: recording a human override back to the audit trail --------


def _orig():
    from labjury.audit import AuditEvent

    return AuditEvent(
        "c1",
        "fp123",
        modalities=frozenset({"text"}),
        candidates=({"label": "nsfw"},),
        answers=({"q": "a"},),
        known_labels=frozenset({"nsfw"}),
        verdict={
            "action": "review",
            "labels": [],
            "scores": {},
            "novel_labels": [],
            "reason": "borderline",
        },
        tenant="acme",
    )


def _res(correlation_id="c1"):
    from labjury.review import ReviewResolution

    return ReviewResolution(
        correlation_id,
        "block",
        ["nsfw"],
        "alice",
        note="confirmed",
        decided_at="2026-10-21T00:00:00+00:00",
    )


def test_correlation_mismatch_raises():
    import pytest

    from labjury.review import override_event

    with pytest.raises(ValueError):
        override_event(_orig(), _res(correlation_id="other"))


def test_verdict_is_human_decision():
    from labjury.audit import verdict_to_dict
    from labjury.review import override_event

    ev = override_event(_orig(), _res())
    assert ev.verdict == verdict_to_dict(_res().to_verdict())
    assert ev.verdict["action"] == "block" and ev.verdict["scores"] == {}


def test_reviewer_provenance():
    from labjury.review import override_event

    ev = override_event(_orig(), _res())
    assert set(ev.provenance) == {"reviewer"}
    ref = ev.provenance["reviewer"]
    assert ref.name == "alice"
    assert ref.params["note"] == "confirmed"
    assert ref.params["decided_at"] == "2026-10-21T00:00:00+00:00"


def test_inputs_carried_forward():
    from labjury.review import override_event

    orig = _orig()
    ev = override_event(orig, _res())
    assert ev.correlation_id == "c1"
    assert ev.input_fingerprint == "fp123"
    assert ev.candidates == orig.candidates
    assert ev.answers == orig.answers
    assert ev.known_labels == orig.known_labels
    assert ev.tenant == "acme"


def test_fresh_event_id():
    from labjury.review import override_event

    orig = _orig()
    ev = override_event(orig, _res())
    assert ev.event_id != orig.event_id


def test_roundtrips():
    from labjury.audit import AuditEvent
    from labjury.review import override_event

    ev = override_event(_orig(), _res())
    assert AuditEvent.from_dict(ev.to_dict()) == ev
