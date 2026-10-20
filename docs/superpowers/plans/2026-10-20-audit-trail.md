# Audit Trail (storage-agnostic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record an immutable, JSON-serializable `AuditEvent` for every engine decision, replay the decision policy from a recorded event, and expose an append-only `AuditLog` contract + conformance suite — with no database and no new dependency.

**Architecture:** A frozen `AuditEvent` with a `to_dict`/`from_dict` seam is the single thing every storage backend touches. The engine captures full decision context (fingerprint, modalities, candidates, answers, taxonomy snapshot, provenance, verdict) and writes it to an injected `AuditLog` (default `NullAuditLog`). `replay_decision` re-runs the policy over the recorded inputs to reproduce the verdict.

**Tech Stack:** Python 3.11+, stdlib only (uuid, datetime, json). No third-party packages, no optional extra.

**Spec:** `docs/superpowers/specs/2026-10-20-audit-trail-design.md`

## Global Constraints

- Core `pyproject.toml` `dependencies` stays `[]`; this step adds no dependency and no extra.
- Never store raw item content in an event — only `input_fingerprint` (the engine's existing cache-key hash) and `modalities`.
- `AuditLog` is append-only: the protocol exposes `record` and `by_correlation` only — no update, no delete.
- No breaking change to existing plugin contracts; `version`/`params` provenance is read via `getattr(plugin, ..., None)`.
- Auditing must never change or break a decision: a failing `record` is swallowed by the engine, and `audit` defaults to a no-op.
- `AuditEvent.to_dict()` is JSON-native (frozensets → sorted lists); `from_dict(to_dict(e)) == e`.

## Review Focus

- **A `record` that raises** (backend down) → `engine.process` still returns the verdict. Pinned in Task 4.
- **Cache-hit decision** → produces a thin `from_cache=True` event, not a full one, and `replay_decision` on it raises `ValueError`. Pinned in Tasks 4 and 3.
- **Taxonomy snapshot at decision time** → replay reproduces novel-label detection using `event.known_labels`, not the live taxonomy. Pinned in Task 3.
- **`NullAuditLog`** → satisfies the `AuditLog` protocol but retains nothing (`by_correlation` always `[]`). Pinned in Task 2.
- **Non-JSON-native field values** (a `frozenset` of modalities, a `bool` answer value) → survive `json.dumps(to_dict(e))` and round-trip. Pinned in Task 1.

---

### Task 1: AuditEvent, ProvenanceRef, and the serialization seam

**Files:**
- Create: `src/labjury/audit.py`
- Modify: `src/labjury/__init__.py` (re-export `AuditEvent`, `ProvenanceRef`)
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `Candidate`, `Question` subclasses (`ChoiceQuestion`, `ScoreQuestion`, `NoulQuestion`) from `labjury.decisions`; `Answer` from `labjury.decisions`.
- Produces:
  - `ProvenanceRef(name: str, version: str | None = None, params: dict | None = None)` — frozen; `.to_dict() -> dict`, classmethod `.from_dict(d) -> ProvenanceRef`.
  - `AuditEvent(correlation_id: str, input_fingerprint: str, *, modalities: frozenset[str] = frozenset(), from_cache: bool = False, used_proposer: bool | None = None, candidates: tuple[dict, ...] = (), answers: tuple[dict, ...] = (), known_labels: frozenset[str] = frozenset(), provenance: dict[str, ProvenanceRef] = {}, verdict: dict | None = None)` — frozen; auto fields `event_id: str` (uuid4 hex) and `occurred_at: str` (UTC ISO-8601) via default_factory; `.to_dict() -> dict`, classmethod `.from_dict(d) -> AuditEvent`.
  - `candidate_to_dict(c: Candidate) -> dict` / `candidate_from_dict(d) -> Candidate`.
  - `answer_to_dict(a: Answer) -> dict` / `answer_from_dict(d) -> Answer`.
  - `question_to_dict(q) -> dict` / `question_from_dict(d) -> Question` (dict carries a `type` tag: `choice`/`score`/`noul`).

- [ ] **Step 1: Write the failing tests** in `tests/test_audit.py`

```python
import json
from labjury.audit import (
    AuditEvent, ProvenanceRef, candidate_to_dict, candidate_from_dict,
    answer_to_dict, answer_from_dict,
)
from labjury.decisions import Candidate, ChoiceQuestion, NoulQuestion, Answer

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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: labjury.audit`.

- [ ] **Step 3: Implement `src/labjury/audit.py`**

Define `ProvenanceRef` and `AuditEvent` as frozen dataclasses with the signatures above. `AuditEvent.to_dict` emits JSON-native values (sort `modalities`/`known_labels` into lists; serialize `provenance` values via `ProvenanceRef.to_dict`); `from_dict` reverses it exactly (rebuild `frozenset`s, `tuple`s, `ProvenanceRef`s) so dataclass equality holds. `question_to_dict` tags the subclass; `question_from_dict` dispatches on the tag. `candidate_*`/`answer_*` compose the question helpers.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Re-export** `AuditEvent` and `ProvenanceRef` from `src/labjury/__init__.py` (import + add to `__all__`).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/audit.py src/labjury/__init__.py tests/test_audit.py
git commit -m "feat: AuditEvent + ProvenanceRef with JSON to_dict/from_dict serialization seam"
```

---

### Task 2: AuditLog protocol, defaults, conformance suite

**Files:**
- Modify: `src/labjury/plugins.py` (add `AuditLog` protocol)
- Modify: `src/labjury/registry.py` (add `"audit_logs"` to `_KINDS`)
- Modify: `pyproject.toml` (declare `[project.entry-points."labjury.audit_logs"]`)
- Modify: `src/labjury/defaults.py` (add `NullAuditLog`, `InMemoryAuditLog`)
- Modify: `src/labjury/testing.py` (add `assert_audit_log_contract`)
- Modify: `src/labjury/__init__.py` (re-export `NullAuditLog`, `InMemoryAuditLog`, `assert_audit_log_contract`)
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `AuditEvent` from `labjury.audit` (Task 1).
- Produces:
  - `AuditLog` protocol (`@runtime_checkable`) in `labjury.plugins`: `async def record(self, event: AuditEvent) -> None`, `async def by_correlation(self, correlation_id: str) -> list[AuditEvent]`.
  - `NullAuditLog` and `InMemoryAuditLog` in `labjury.defaults`, both implementing the protocol.
  - `async def assert_audit_log_contract(make_log: Callable[[], AuditLog]) -> None` in `labjury.testing`.

- [ ] **Step 1: Write the failing tests** in `tests/test_audit.py`

```python
from labjury.plugins import AuditLog
from labjury.defaults import NullAuditLog, InMemoryAuditLog
from labjury.testing import assert_audit_log_contract

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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_audit.py -k "audit_log or append_only or registry_kind" -v`
Expected: FAIL — `AuditLog`/`NullAuditLog`/`assert_audit_log_contract` undefined.

- [ ] **Step 3: Implement the pieces**

Add the `AuditLog` protocol to `plugins.py`; add `"audit_logs"` to `registry._KINDS`; declare the empty entry-point group in `pyproject.toml`; implement `NullAuditLog` (record no-op, `by_correlation` returns `[]`) and `InMemoryAuditLog` (append to a list, `by_correlation` filters in insertion order) in `defaults.py`; implement `assert_audit_log_contract` in `testing.py` — record two events for one id and one for another, assert `by_correlation` returns the two in order, returns `[]` for an unknown id, and assert the log type has no `update`/`delete` attribute.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Re-export** `NullAuditLog`, `InMemoryAuditLog`, `assert_audit_log_contract` from `__init__.py`.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/plugins.py src/labjury/registry.py pyproject.toml src/labjury/defaults.py src/labjury/testing.py src/labjury/__init__.py tests/test_audit.py
git commit -m "feat: append-only AuditLog protocol, Null/InMemory defaults, conformance suite"
```

---

### Task 3: Deterministic replay

**Files:**
- Modify: `src/labjury/audit.py` (add `replay_decision`, `verdict_matches`)
- Modify: `src/labjury/__init__.py` (re-export both)
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `AuditEvent`, `candidate_from_dict`, `answer_from_dict` from `labjury.audit` (Task 1); `RecallBiasedPolicy` from `labjury.policies`; `Verdict`/`Action` from `labjury.results`; `State` from `labjury.state`.
- Produces:
  - `async def replay_decision(event: AuditEvent, policy) -> Verdict` — raises `ValueError` if `event.from_cache`.
  - `def verdict_matches(event: AuditEvent, verdict: Verdict) -> bool` — compares a `Verdict` to `event.verdict` (the recorded dict).

- [ ] **Step 1: Write the failing tests** in `tests/test_audit.py`

```python
from labjury.audit import replay_decision, verdict_matches
from labjury.policies import RecallBiasedPolicy

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
    # empty known-label snapshot -> the accepted label is novel in replay
    event = _decided_event(known=frozenset())
    verdict = await replay_decision(event, RecallBiasedPolicy())
    assert "food" in verdict.novel_labels

async def test_replay_of_cache_hit_raises():
    import pytest
    event = AuditEvent("i1", "fp1", from_cache=True, verdict={"action": "accept",
        "labels": [], "scores": {}, "novel_labels": [], "reason": "cached"})
    with pytest.raises(ValueError):
        await replay_decision(event, RecallBiasedPolicy())
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_audit.py -k replay -v`
Expected: FAIL — `replay_decision` undefined.

- [ ] **Step 3: Implement `replay_decision` and `verdict_matches` in `audit.py`**

`replay_decision`: raise `ValueError` when `event.from_cache`; rebuild `Candidate`s and `Answer`s from the recorded dicts; build a frozen read-only taxonomy whose `is_known` is true exactly for `event.known_labels` (a tiny local class satisfying the methods `policy.decide` calls — `is_known`, `propose`, `promote`, `known_labels`, `proposed_labels` — where writes are no-ops); call `await policy.decide(State(), candidates, answers, taxonomy)` and return its `Verdict`. `verdict_matches`: compare `verdict.action.value`, `verdict.labels`, `verdict.novel_labels`, `verdict.reason` against `event.verdict`.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_audit.py -k replay -v`
Expected: PASS.

- [ ] **Step 5: Re-export** `replay_decision`, `verdict_matches` from `__init__.py`.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/audit.py src/labjury/__init__.py tests/test_audit.py
git commit -m "feat: deterministic replay of a recorded decision from its audit event"
```

---

### Task 4: Policy params + engine capture

**Files:**
- Modify: `src/labjury/policies.py` (add `params` property to `RecallBiasedPolicy`)
- Modify: `src/labjury/engine.py` (inject `audit`, capture context, record events)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `AuditEvent`, `candidate_to_dict`, `answer_to_dict` from `labjury.audit` (Task 1); `AuditLog`, `NullAuditLog` (Tasks 2); `ProvenanceRef` (Task 1).
- Produces: `Engine(..., *, audit: AuditLog | None = None, ...)`; one `AuditEvent` recorded per decided item and per cache hit.

- [ ] **Step 1: Write the failing tests** in `tests/test_engine.py`

```python
from labjury.audit import AuditEvent
from labjury.defaults import InMemoryAuditLog

async def test_decided_item_records_full_event():
    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)  # helper gains an audit kwarg
    await eng.process(Item("i1", {"text": "x"}))
    [e] = await audit.by_correlation("i1")
    assert e.from_cache is False and e.used_proposer is True
    assert e.input_fingerprint == eng._key(Item("i1", {"text": "x"}))  # fingerprint, not content
    assert e.candidates and e.answers
    assert "policy" in e.provenance and "scorer" in e.provenance
    assert e.provenance["policy"].params is not None
    assert e.known_labels == frozenset()  # fresh taxonomy
    assert e.verdict["action"] in ("accept", "review")

async def test_cache_hit_records_thin_event():
    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    item = Item("i1", {"text": "x"})
    await eng.cache.put(eng._key(item), Verdict(Action.ACCEPT, ["food"], {}, [], "cached"))
    await eng.process(item)
    [e] = await audit.by_correlation("i1")
    assert e.from_cache is True and e.candidates == () and e.verdict["reason"] == "cached"

async def test_audit_failure_does_not_break_process():
    class Boom:
        async def record(self, event): raise RuntimeError("down")
        async def by_correlation(self, cid): return []
    eng = make_engine(audit=Boom())
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.status in (Status.DECIDED, Status.REVIEW)

def test_recall_biased_policy_exposes_params():
    from labjury.policies import RecallBiasedPolicy
    assert RecallBiasedPolicy().params == {"accept_threshold": 0.85, "clean_threshold": 0.9}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_engine.py -k "event or params or audit" -v`
Expected: FAIL — `make_engine` has no `audit` kwarg / `params` undefined / no events recorded.

- [ ] **Step 3: Add `params` to `RecallBiasedPolicy`** in `policies.py`

A read-only `params` property returning `{"accept_threshold": self._accept, "clean_threshold": self._clean}`.

- [ ] **Step 4: Implement engine capture** in `engine.py`

Add keyword-only `audit: AuditLog | None = None`; store `self._audit = audit or NullAuditLog()`. Fetch `known = frozenset(await self._taxonomy.known_labels())` once on the decision path and reuse it for the proposer `ProposalContext` and the event. On a cache hit, build and record a thin `AuditEvent(item.id, key, from_cache=True, verdict=_verdict_to_dict(cached))`. On a full decision, after the verdict, build an `AuditEvent` with `modalities`, `used_proposer`, `candidates`/`answers` via the Task 1 helpers, `known_labels=known`, `provenance={"scorer": ProvenanceRef(...), "policy": ProvenanceRef(...)}`, and `verdict=_verdict_to_dict(verdict)`. Record via a private `_record_safe` that swallows exceptions so a failing backend never breaks `process`. Add a module-local `_verdict_to_dict(v: Verdict) -> dict`.

- [ ] **Step 5: Update the `make_engine` test helper** in `tests/test_engine.py` to accept and pass an `audit` kwarg (default `None`).

- [ ] **Step 6: Run to verify they pass**

Run: `python -m pytest tests/test_engine.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/labjury/policies.py src/labjury/engine.py tests/test_engine.py
git commit -m "feat: engine records an immutable audit event per decision and cache hit"
```

---

### Task 5: Audit documentation

**Files:**
- Create: `docs/audit-trail.md`
- Modify: `README.md`, `README.vi.md` (short pointer)

**Interfaces:**
- Consumes: the finished `AuditEvent`, `AuditLog`, defaults, `replay_decision`, and `assert_audit_log_contract` (Tasks 1–4).
- Produces: no code.

- [ ] **Step 1: Write `docs/audit-trail.md`**

Cover: what an `AuditEvent` records and the no-raw-content rule; wiring `Engine(..., audit=InMemoryAuditLog())`; the `AuditLog` protocol and that LabJury ships **no database** — bring your own storage (Kafka/S3/SIEM/SQL) via the `to_dict`/`from_dict` seam, verified with `assert_audit_log_contract`; and replaying a decision with `replay_decision`. Include a minimal custom-backend example.

- [ ] **Step 2: Add a short pointer** in `README.md` and `README.vi.md` linking `docs/audit-trail.md`, noting audit is opt-in and storage-agnostic.

- [ ] **Step 3: Verify the documented example matches shipped symbols** (read-through against Tasks 1–4; no test).

- [ ] **Step 4: Commit**

```bash
git add docs/audit-trail.md README.md README.vi.md
git commit -m "docs: storage-agnostic audit trail and bring-your-own AuditLog"
```
