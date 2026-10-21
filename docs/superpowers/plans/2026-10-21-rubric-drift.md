# Rubric-vs-registry drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `labjury.audit.rubric_drift(event, store)` + the `RubricDrift` record — a pure async reproducibility check that compares each recorded candidate's rubric against what the registry holds for that version; no core/contract change.

**Architecture:** A pure read in `labjury.audit` over an existing `AuditEvent` and a duck-typed `RubricStore` (`async get(label, version) -> Rubric | None`). It composes the module's existing `question_to_dict`. Detection only — it returns a list of `RubricDrift` (empty = faithful), never mutates.

**Tech Stack:** Python 3.11+ stdlib; pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-10-21-rubric-drift-design.md`

## Global Constraints

- Pure core, `dependencies = []`; lives in `labjury.audit`; audit does not import `labjury.plugins`/`rubrics` (store is duck-typed).
- No engine change, no plugin-contract change, no mutation.
- Re-exported top-level (`RubricDrift`, `rubric_drift`) — additive to `__all__`.
- TDD throughout; commit per task.

## Review Focus

- `rubric_version` absent from registry → one drift, `registry_question=None` — Task 1 (`test_drift_version_absent`).
- Recorded question differs from registry → one drift — Task 1 (`test_drift_question_differs`).
- `rubric_version=None` candidate → skipped, no `get` call — Task 1 (`test_none_version_skipped`).
- All-consistent / no-candidate event → `[]` — Task 1 (`test_consistent_no_drift`, `test_no_candidates_no_drift`).

---

### Task 1: `RubricDrift` + `rubric_drift`

**Files:**
- Modify: `src/labjury/audit.py` (add `RubricDrift`, `rubric_drift`)
- Modify: `src/labjury/__init__.py` (re-export both; add to `__all__`)
- Test: `tests/test_rubric_drift.py`

**Interfaces:**
- Consumes: `AuditEvent` (its `candidates: tuple[dict, ...]`, each `{label, kind, question, rubric_version}`); the existing `question_to_dict`; a duck-typed store with `async get(label, version) -> Rubric | None` (Rubric has `.question`).
- Produces:
  - `labjury.audit.RubricDrift` — frozen dataclass `label: str`, `version: str`, `reason: str`, `recorded_question: dict`, `registry_question: dict | None`.
  - `async labjury.audit.rubric_drift(event: AuditEvent, store) -> list[RubricDrift]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_rubric_drift.py`

```python
from labjury.audit import AuditEvent, RubricDrift, candidate_to_dict, rubric_drift
from labjury.decisions import Candidate, NoulQuestion
from labjury.rubrics import InMemoryRubricStore


def _event(*candidates):
    return AuditEvent("c1", "fp", candidates=tuple(candidate_to_dict(c) for c in candidates))


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
    event = _event(Candidate("nsfw", "noul", NoulQuestion("k", "recorded?"), rubric_version="v1"))
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_rubric_drift.py -v`
Expected: FAIL — `cannot import name 'RubricDrift'`.

- [ ] **Step 3: Implement in `src/labjury/audit.py`**

Add the `RubricDrift` frozen dataclass and `async def rubric_drift(event, store)`: iterate `event.candidates`; for each dict, read `version = cand.get("rubric_version")`, skip if `None`; `stored = await store.get(cand["label"], version)`; if `stored is None` append `RubricDrift(label, version, "version absent from registry", cand["question"], None)`; else `reg_q = question_to_dict(stored.question)` and if `reg_q != cand["question"]` append `RubricDrift(label, version, "question differs from registry", cand["question"], reg_q)`. Return the list.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_rubric_drift.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Re-export** — add `RubricDrift`, `rubric_drift` to the `labjury.audit` import block and the `# audit` group of `__all__` in `src/labjury/__init__.py`.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS (all prior + 5 new); `PYTHONPATH=src python -c "import labjury; labjury.rubric_drift; labjury.RubricDrift"`.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/audit.py src/labjury/__init__.py tests/test_rubric_drift.py
git commit -m "feat: rubric_drift — detect recorded-rubric vs registry divergence"
```

---

### Task 2: Docs

**Files:**
- Modify: `docs/reproducibility.md` (add a "Rubric drift" subsection)
- Modify: `README.md`, `README.vi.md` (one-line pointer where reproducibility/replay is mentioned)

**Interfaces:**
- Consumes: `rubric_drift`, `RubricDrift` (Task 1).

- [ ] **Step 1: Document in `docs/reproducibility.md`**

A "Rubric drift" subsection: what it detects (recorded `Candidate.rubric_version` question vs `RubricStore.get`), that published versions are immutable so any mismatch is a real signal, the two reasons (absent / differs), that `None` versions are skipped and cache-hit events yield `[]`, and that it's detection-only (deployer decides the response). Show the call: `drift = await lj.rubric_drift(event, store)`.

- [ ] **Step 2: README pointers**

Where reproducibility/`verify_replay` is mentioned in `README.md`, add a sentence that rubric-vs-registry drift is also checkable via `lj.rubric_drift`; mirror in `README.vi.md`.

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS (docs-only; no code change).

- [ ] **Step 4: Commit**

```bash
git add docs/reproducibility.md README.md README.vi.md
git commit -m "docs: rubric drift check in reproducibility + README pointers"
```
