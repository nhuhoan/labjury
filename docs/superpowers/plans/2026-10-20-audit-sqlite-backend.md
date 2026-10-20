# SQLite Audit-Log Reference Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one durable, dependency-free `AuditLog` reference backend
(`SqliteAuditLog`) under `labjury.contrib`, proven by the shipped conformance
suite and a restart-survival test.

**Architecture:** A single class wraps the stdlib `sqlite3` module. Every
blocking call runs under `asyncio.to_thread` so the event loop is never blocked;
each operation opens a short-lived connection on the thread (sidestepping
`sqlite3`'s thread affinity). Events are stored as `json.dumps(event.to_dict())`
and read back via `AuditEvent.from_dict` — the backend touches only the
serialization seam, never LabJury's internal types.

**Tech Stack:** Python stdlib `sqlite3`, `asyncio.to_thread`, `json`. No new
third-party dependency.

**Spec:** `docs/superpowers/specs/2026-10-20-audit-sqlite-backend-design.md`

## Global Constraints

- Zero new third-party dependency; no new install extra (`sqlite3` is stdlib).
- The core never imports `labjury.contrib` — this backend lives only in contrib.
- Append-only: the class exposes `record` and `by_correlation` only; no `update`,
  no `delete` (the conformance suite asserts the type lacks both).
- Not entry-point registered (needs a `path` arg; registry uses zero-arg
  factories) and not re-exported from top-level `labjury` — used via
  `from labjury.contrib.sqlite_audit import SqliteAuditLog`.
- Honor the `AuditLog` protocol exactly: `async def record(self, event) -> None`,
  `async def by_correlation(self, correlation_id) -> list[AuditEvent]`.
- `by_correlation` returns events in insertion order.

## Review Focus

- **Concurrent writes** from multiple `asyncio.to_thread` threads must not raise
  "database is locked" nor lose events — WAL mode + a connect `timeout`; pinned
  by a test in Task 1.
- **`table` isolation**: two logs sharing one file but different `table` names
  must not see each other's events — pinned by a test in Task 1.
- **Full-field fidelity**: an `AuditEvent` with every field populated
  (modalities, candidates, answers, known_labels, provenance, verdict) must
  survive storage and retrieval equal — pinned by a test in Task 1.
- **Restart survival**: events recorded by one instance must be readable by a
  fresh instance on the same path — pinned by a test in Task 1.
- Core-import isolation is already pinned by the subprocess test in
  `tests/test_redis_taxonomy.py` (asserts top-level import pulls in neither
  `contrib` nor its deps); no new test needed.

---

### Task 1: `SqliteAuditLog` backend

**Files:**
- Create: `src/labjury/contrib/sqlite_audit.py`
- Test: `tests/test_sqlite_audit.py`

**Interfaces:**
- Consumes: `labjury.audit.AuditEvent` (with `.to_dict()` / `.from_dict()`),
  `labjury.audit.ProvenanceRef`, `labjury.audit.candidate_to_dict`,
  `labjury.audit.answer_to_dict`; `labjury.decisions.Candidate`,
  `ChoiceQuestion`, `Answer`; `labjury.testing.assert_audit_log_contract`.
- Produces: `SqliteAuditLog(path: str, table: str = "labjury_audit")` with
  `async def record(self, event: AuditEvent) -> None` and
  `async def by_correlation(self, correlation_id: str) -> list[AuditEvent]`.

- [ ] **Step 1: Write the failing conformance + durability + fidelity tests**

```python
import asyncio
from labjury.audit import (
    AuditEvent, ProvenanceRef, candidate_to_dict, answer_to_dict,
)
from labjury.decisions import Answer, Candidate, ChoiceQuestion
from labjury.contrib.sqlite_audit import SqliteAuditLog
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
        candidates=(candidate_to_dict(
            Candidate("food", "tag", ChoiceQuestion("q", "food?", ["food"]))),),
        answers=(answer_to_dict(
            Answer("q", value="food", confidence=0.9, distribution={"food": 0.9})),),
        known_labels=frozenset({"a", "b"}),
        provenance={"policy": ProvenanceRef("RecallBiasedPolicy", None,
                                            {"accept_threshold": 0.85})},
        verdict={"action": "accept", "labels": ["food"],
                 "novel_labels": [], "reason": "ok"},
    )
    log = SqliteAuditLog(str(tmp_path / "audit.db"))
    await log.record(event)
    [got] = await log.by_correlation("c1")
    assert got == event


async def test_concurrent_writes_all_land(tmp_path):
    log = SqliteAuditLog(str(tmp_path / "audit.db"))
    await asyncio.gather(*(log.record(AuditEvent("c1", f"fp-{i}")) for i in range(50)))
    assert len(await log.by_correlation("c1")) == 50
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sqlite_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'labjury.contrib.sqlite_audit'`.

- [ ] **Step 3: Implement `SqliteAuditLog` in `src/labjury/contrib/sqlite_audit.py`**

  - `__init__(self, path, table="labjury_audit")`: store `path` and `table`;
    open a connection synchronously once to run, in a single script:
    `PRAGMA journal_mode=WAL;`, `CREATE TABLE IF NOT EXISTS <table> (seq INTEGER
    PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, correlation_id TEXT NOT
    NULL, payload TEXT NOT NULL);`, `CREATE INDEX IF NOT EXISTS <table>_corr ON
    <table>(correlation_id);` then close. `table` is interpolated into the SQL
    (identifier, not a bindable parameter).
  - A private `_connect(self)` helper: `sqlite3.connect(self._path, timeout=30)`.
  - `record`: run under `asyncio.to_thread` a function that opens a connection,
    `INSERT INTO <table> (event_id, correlation_id, payload) VALUES (?, ?, ?)`
    with `event.event_id, event.correlation_id, json.dumps(event.to_dict())`,
    commits, closes.
  - `by_correlation`: run under `asyncio.to_thread` a function that opens a
    connection, `SELECT payload FROM <table> WHERE correlation_id = ? ORDER BY
    seq`, returns `[AuditEvent.from_dict(json.loads(p)) for (p,) in rows]`,
    closes.
  - No `update`/`delete` methods.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sqlite_audit.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `python -m pytest`
Expected: all pass (prior count + 5), 1 skipped (the real-Redis integration test).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/contrib/sqlite_audit.py tests/test_sqlite_audit.py
git commit -m "feat: SqliteAuditLog durable audit-log reference backend"
```

---

### Task 2: Documentation

**Files:**
- Modify: `docs/audit-trail.md` (add a "SQLite reference backend" subsection
  after the existing "Bring your own storage" / JSONL example)
- Modify: `README.md` (one-line pointer in the audit-trail subsection)
- Modify: `README.vi.md` (the matching Vietnamese one-line pointer)

**Interfaces:**
- Consumes: `SqliteAuditLog(path, table="labjury_audit")` from Task 1.
- Produces: nothing code depends on.

- [ ] **Step 1: Add the SQLite subsection to `docs/audit-trail.md`**

Show the minimal usage and that it is one reference backend, not a requirement:
```python
from labjury.contrib.sqlite_audit import SqliteAuditLog
engine = lj.Engine(..., audit=SqliteAuditLog("audit.db"))
```
State: zero extra install (stdlib `sqlite3`), durable across restart, append-only,
and that Postgres/others are the same shape via the `AuditLog` protocol +
`to_dict`/`from_dict` seam.

- [ ] **Step 2: Add the one-line pointers to `README.md` and `README.vi.md`**

In each audit-trail subsection, one sentence that a durable SQLite reference
backend ships (`labjury.contrib.sqlite_audit.SqliteAuditLog`, no extra needed),
linking `docs/audit-trail.md`.

- [ ] **Step 3: Verify the docs reference real symbols**

Run: `python -c "from labjury.contrib.sqlite_audit import SqliteAuditLog; SqliteAuditLog(':memory:')"`
Expected: no error (the documented import path and constructor are valid).

- [ ] **Step 4: Commit**

```bash
git add docs/audit-trail.md README.md README.vi.md
git commit -m "docs: SQLite audit-log reference backend"
```
