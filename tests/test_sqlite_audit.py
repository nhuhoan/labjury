import asyncio

from labjury.audit import (
    AuditEvent,
    ProvenanceRef,
    answer_to_dict,
    candidate_to_dict,
)
from labjury.contrib.sqlite_audit import SqliteAuditLog
from labjury.decisions import Answer, Candidate, ChoiceQuestion
from labjury.testing import assert_audit_log_contract


async def test_sqlite_audit_satisfies_contract(tmp_path):
    db = str(tmp_path / "audit.db")
    await assert_audit_log_contract(lambda: SqliteAuditLog(db))


async def test_survives_reopen(tmp_path):
    db = str(tmp_path / "audit.db")
    log = SqliteAuditLog(db)
    await log.record(AuditEvent("c1", "fp-1"))
    del log  # drop the instance; the file is the only state
    reopened = SqliteAuditLog(db)
    events = await reopened.by_correlation("c1")
    assert len(events) == 1 and events[0].input_fingerprint == "fp-1"


async def test_tables_are_isolated(tmp_path):
    db = str(tmp_path / "audit.db")
    a = SqliteAuditLog(db, table="audit_a")
    b = SqliteAuditLog(db, table="audit_b")
    await a.record(AuditEvent("c1", "fp-a"))
    assert await a.by_correlation("c1") != []
    assert await b.by_correlation("c1") == []


async def test_round_trips_every_field(tmp_path):
    event = AuditEvent(
        correlation_id="c1",
        input_fingerprint="fp-1",
        modalities=frozenset({"text", "image"}),
        from_cache=False,
        used_proposer=True,
        candidates=(
            candidate_to_dict(
                Candidate("food", "tag", ChoiceQuestion("q", "food?", ["food"]))
            ),
        ),
        answers=(
            answer_to_dict(
                Answer("q", value="food", confidence=0.9, distribution={"food": 0.9})
            ),
        ),
        known_labels=frozenset({"a", "b"}),
        provenance={
            "policy": ProvenanceRef(
                "RecallBiasedPolicy", None, {"accept_threshold": 0.85}
            )
        },
        verdict={
            "action": "accept",
            "labels": ["food"],
            "novel_labels": [],
            "reason": "ok",
        },
    )
    log = SqliteAuditLog(str(tmp_path / "audit.db"))
    await log.record(event)
    [got] = await log.by_correlation("c1")
    assert got == event


async def test_concurrent_writes_all_land(tmp_path):
    log = SqliteAuditLog(str(tmp_path / "audit.db"))
    await asyncio.gather(
        *(log.record(AuditEvent("c1", f"fp-{i}")) for i in range(50))
    )
    assert len(await log.by_correlation("c1")) == 50
