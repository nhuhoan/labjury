from labjury.audit import AuditEvent, RubricDrift, candidate_to_dict, rubric_drift
from labjury.decisions import Candidate, NoulQuestion
from labjury.rubrics import InMemoryRubricStore


def _event(*candidates):
    return AuditEvent(
        "c1", "fp", candidates=tuple(candidate_to_dict(c) for c in candidates)
    )


async def _store(*rubrics):
    s = InMemoryRubricStore()
    for label, q, ver in rubrics:
        await s.register(label, q, ver)
    return s


async def test_consistent_no_drift():
    q = NoulQuestion("k", "p?")
    store = await _store(("nsfw", q, "v1"))
    event = _event(Candidate("nsfw", "noul", q, rubric_version="v1"))
    assert await rubric_drift(event, store) == []


async def test_drift_version_absent():
    q = NoulQuestion("k", "p?")
    store = await _store()  # empty registry
    event = _event(Candidate("nsfw", "noul", q, rubric_version="v1"))
    drift = await rubric_drift(event, store)
    assert len(drift) == 1
    assert drift[0].label == "nsfw" and drift[0].version == "v1"
    assert drift[0].registry_question is None


async def test_drift_question_differs():
    store = await _store(("nsfw", NoulQuestion("k", "registry?"), "v1"))
    event = _event(
        Candidate("nsfw", "noul", NoulQuestion("k", "recorded?"), rubric_version="v1")
    )
    drift = await rubric_drift(event, store)
    assert len(drift) == 1
    assert drift[0].recorded_question["prompt"] == "recorded?"
    assert drift[0].registry_question["prompt"] == "registry?"


async def test_none_version_skipped():
    q = NoulQuestion("k", "p?")
    event = _event(Candidate("nsfw", "noul", q))  # rubric_version defaults None

    class _Boom:
        async def get(self, label, version):
            raise AssertionError("get must not be called for a None rubric_version")

    assert await rubric_drift(event, _Boom()) == []


async def test_no_candidates_no_drift():
    assert await rubric_drift(AuditEvent("c1", "fp"), await _store()) == []
