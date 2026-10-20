# Rubric Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a versioned, storage-agnostic `label → Question` registry — a `Rubric` value object, a `RubricStore` protocol, a zero-dep `InMemoryRubricStore` reference and its conformance suite — and thread a rubric-version handle through the audit trail via an optional `Candidate.rubric_version` field, with no engine change and no break to the plugin contract.

**Architecture:** A `Rubric(label, question, version)` value object in `labjury.rubrics` and a `RubricStore` protocol in `labjury.plugins` (shaped like `TaxonomyStore`): `register`/`resolve`/`get`/`history`. `InMemoryRubricStore` keeps per-label insertion-ordered versions; a published version is immutable. `assert_rubric_store_contract` ships in `labjury.testing`. The reproducibility link is one additive, defaulted field on `Candidate` (`rubric_version: str | None = None`) that the existing `candidate_to_dict`/`candidate_from_dict` seam carries into the `AuditEvent` — the engine stays rubric-agnostic. Zero new dependency; mechanism in core, re-exported top-level — the same pattern as `reliability`/`redaction`.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`, `typing`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-rubric-registry-design.md`

## Global Constraints

- Core `dependencies = []`; this mechanism is stdlib-only and lives in core (`labjury.rubrics` + protocol in `labjury.plugins`, conformance in `labjury.testing`). Core never imports `labjury.contrib`.
- Never break the public plugin contract. The only contract touch is an optional, defaulted field on `Candidate` — additive, like `latency_ms` on `ItemResult`. No existing signature changes; no `Proposer`/`Scorer`/`DecisionPolicy`/`Engine` change.
- A published `(label, version)` is immutable: re-registering the same version with the same question is idempotent; with a different question it raises `ValueError`.
- No durable backend, no entry-point group (DI-style store, used by direct import — like `TaxonomyStore` backends), no built-in rubrics, no engine auto-wiring.
- Conformance suite ships in the installed package (`labjury.testing`), not under `tests/`.
- TDD throughout; commit per task.

## Review Focus

- Re-publishing a version with a **different** question raises `ValueError`; with the **same** question is idempotent — pinned in Task 1 (`test_version_is_immutable_once_published`, `test_reregister_same_version_same_question_is_idempotent`).
- `resolve` returns the **latest** registered version after several registrations — pinned in Task 1 (`test_resolve_returns_latest_version`).
- `get(label, old_version)` still returns the **old** rubric after a newer one is registered — pinned in Task 1 (`test_get_old_version_survives_supersession`).
- `resolve`/`get`/`history` on an **unregistered** label return `None`/`None`/`[]`, never `KeyError` — pinned in Task 1 (`test_unregistered_label_is_empty`).
- A `Candidate` built **without** `rubric_version` round-trips through the audit seam with `rubric_version is None` (backward-compatible with pre-registry candidates) — pinned in Task 2 (`test_candidate_without_rubric_version_roundtrips`).

---

### Task 1: `Rubric` value object + `RubricStore` protocol + `InMemoryRubricStore` + conformance suite

**Files:**
- Create: `src/labjury/rubrics.py`
- Modify: `src/labjury/plugins.py` (add `RubricStore` protocol)
- Modify: `src/labjury/testing.py` (add `assert_rubric_store_contract`)
- Test: `tests/test_rubrics.py`

**Interfaces:**
- Consumes: `Question` (and a concrete e.g. `NoulQuestion`/`ChoiceQuestion`) from `labjury.decisions`.
- Produces:
  - `labjury.rubrics.Rubric` — frozen dataclass: `label: str`, `question: Question`, `version: str`.
  - `labjury.rubrics.InMemoryRubricStore()` — the `RubricStore` methods below.
  - `labjury.plugins.RubricStore` — `@runtime_checkable` Protocol:
    - `async def register(self, label: str, question: Question, version: str) -> Rubric`
    - `async def resolve(self, label: str) -> Rubric | None`
    - `async def get(self, label: str, version: str) -> Rubric | None`
    - `async def history(self, label: str) -> list[str]`
  - `labjury.testing.assert_rubric_store_contract(make_store)` — zero-arg factory (sync or async), drives every invariant, raises `AssertionError`/`ValueError` on violation.
- Semantics: `register` stores a versioned rubric and makes it current; same `(label, version)` + equal question → returns stored rubric (idempotent); same `(label, version)` + different question → `ValueError`. `resolve` → most recently registered rubric for the label or `None`. `get` → the exact version or `None`. `history` → version strings in registration order or `[]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_rubrics.py`

Use a small question factory in tests, e.g. `NoulQuestion(key, prompt)`.

```python
import pytest
from labjury.decisions import NoulQuestion
from labjury.plugins import RubricStore
from labjury.rubrics import InMemoryRubricStore, Rubric
from labjury.testing import assert_rubric_store_contract


def _q(prompt="graphic violence?"):
    return NoulQuestion("violence", prompt)


async def test_register_then_resolve():
    store = InMemoryRubricStore()
    r = await store.register("violence", _q(), "v1")
    assert r == Rubric("violence", _q(), "v1")
    assert await store.resolve("violence") == r


async def test_resolve_returns_latest_version():
    store = InMemoryRubricStore()
    await store.register("violence", _q("old"), "v1")
    await store.register("violence", _q("new"), "v2")
    assert (await store.resolve("violence")).version == "v2"


async def test_get_old_version_survives_supersession():
    store = InMemoryRubricStore()
    await store.register("violence", _q("old"), "v1")
    await store.register("violence", _q("new"), "v2")
    assert (await store.get("violence", "v1")).question == _q("old")


async def test_history_in_registration_order():
    store = InMemoryRubricStore()
    await store.register("violence", _q(), "v1")
    await store.register("violence", _q("x"), "v2")
    assert await store.history("violence") == ["v1", "v2"]


async def test_version_is_immutable_once_published():
    store = InMemoryRubricStore()
    await store.register("violence", _q("first"), "v1")
    with pytest.raises(ValueError):
        await store.register("violence", _q("changed"), "v1")


async def test_reregister_same_version_same_question_is_idempotent():
    store = InMemoryRubricStore()
    await store.register("violence", _q(), "v1")
    r = await store.register("violence", _q(), "v1")
    assert r.version == "v1"
    assert await store.history("violence") == ["v1"]


async def test_unregistered_label_is_empty():
    store = InMemoryRubricStore()
    assert await store.resolve("nope") is None
    assert await store.get("nope", "v1") is None
    assert await store.history("nope") == []


def test_in_memory_store_is_a_rubric_store():
    assert isinstance(InMemoryRubricStore(), RubricStore)


async def test_conformance_suite_passes_for_in_memory():
    await assert_rubric_store_contract(InMemoryRubricStore)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_rubrics.py -v`
Expected: FAIL — `cannot import name 'InMemoryRubricStore'` / `Rubric` / `RubricStore` / `assert_rubric_store_contract`.

- [ ] **Step 3: Add the `RubricStore` protocol to `src/labjury/plugins.py`**

A `@runtime_checkable` Protocol with the four async methods from Interfaces, placed beside `TaxonomyStore`. Import `Question` from `labjury.decisions` (already imported there) and `Rubric` from `labjury.rubrics` for the annotations; if that creates an import cycle, annotate the return as `"Rubric"` / use `from __future__ import annotations` (already present) and a `TYPE_CHECKING` import. A short docstring: versioned `label → Question`; a published version is immutable; LabJury owns the registry, not the rubric content.

- [ ] **Step 4: Implement `Rubric` + `InMemoryRubricStore` in `src/labjury/rubrics.py`**

`Rubric` = `@dataclass(frozen=True)` with `label`, `question`, `version`. `InMemoryRubricStore` holds `self._by_label: dict[str, dict[str, Rubric]]` (inner dict preserves insertion order). `register`: if the version exists for the label and its question equals the new one, return it; if it exists with a different question, raise `ValueError`; else store `Rubric(label, question, version)` and return it. `resolve`: last value of the inner dict or `None`. `get`: inner dict `.get(version)`. `history`: `list(inner)` or `[]`.

- [ ] **Step 5: Add `assert_rubric_store_contract` to `src/labjury/testing.py`**

Mirror `assert_taxonomy_store_contract`: a `RubricStoreFactory` type, reuse the `_make` await-or-not helper (or a local equivalent). Assert, each on a fresh store: unregistered label → `resolve`/`get` `None`, `history` `[]`; register → `resolve` returns it and `history == [version]`; two versions → `resolve` is the second, `get(first)` still returns the first, `history == [v1, v2]`; re-register same version + different question → `ValueError` (use `try/except ValueError` else `assert False`).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_rubrics.py -v`
Expected: PASS (all of Step 1).

- [ ] **Step 7: Commit**

```bash
git add src/labjury/rubrics.py src/labjury/plugins.py src/labjury/testing.py tests/test_rubrics.py
git commit -m "feat: versioned RubricStore seam + InMemoryRubricStore + conformance suite"
```

---

### Task 2: Reproducibility link — `Candidate.rubric_version` through the audit seam

**Files:**
- Modify: `src/labjury/decisions.py` (add optional field to `Candidate`)
- Modify: `src/labjury/audit.py` (`candidate_to_dict`/`candidate_from_dict`)
- Test: `tests/test_audit.py` (add cases; if no such file, `tests/test_rubrics.py`)

**Interfaces:**
- Consumes: `Candidate` from `labjury.decisions`; `candidate_to_dict`/`candidate_from_dict` from `labjury.audit`.
- Produces: `Candidate` gains `rubric_version: str | None = None` (last field, defaulted). `candidate_to_dict(c)` includes `"rubric_version": c.rubric_version`; `candidate_from_dict(d)` reads `d.get("rubric_version")`.

- [ ] **Step 1: Write the failing tests**

Place in the existing audit test module if present (check `tests/test_audit.py`), else in `tests/test_rubrics.py`.

```python
from labjury.audit import candidate_from_dict, candidate_to_dict
from labjury.decisions import Candidate, NoulQuestion


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_audit.py -k rubric_version -v` (or the module chosen)
Expected: FAIL — `Candidate.__init__() got an unexpected keyword argument 'rubric_version'` / `KeyError: 'rubric_version'`.

- [ ] **Step 3: Add the field to `Candidate` in `src/labjury/decisions.py`**

Append `rubric_version: str | None = None` as the last field of the `Candidate` dataclass, with a one-line comment that it links a candidate to the registered rubric revision it was built from (for audit/reproducibility).

- [ ] **Step 4: Carry it through the seam in `src/labjury/audit.py`**

`candidate_to_dict`: add `"rubric_version": c.rubric_version`. `candidate_from_dict`: pass `rubric_version=d.get("rubric_version")` to the `Candidate(...)` call (so older recorded dicts without the key decode to `None`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_audit.py tests/test_rubrics.py -v` (plus the module chosen)
Expected: PASS.

- [ ] **Step 6: Run the full suite** (the `Candidate` change touches shared code)

Run: `pytest`
Expected: PASS (all prior tests unaffected — the field is defaulted).

- [ ] **Step 7: Commit**

```bash
git add src/labjury/decisions.py src/labjury/audit.py tests/
git commit -m "feat: Candidate.rubric_version — reproducibility link into the audit trail"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/rubric-registry.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `RubricStore` (Task 1, from `labjury.plugins`); `Rubric`, `InMemoryRubricStore` (Task 1, from `labjury.rubrics`); `assert_rubric_store_contract` (Task 1, from `labjury.testing`).
- Produces: all four names importable as `labjury.<name>`.

- [ ] **Step 1: Add the four names to `tests/test_public_api.py`**

Append `"Rubric"`, `"RubricStore"`, `"InMemoryRubricStore"`, `"assert_rubric_store_contract"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: Rubric`.

- [ ] **Step 3: Re-export the names in `src/labjury/__init__.py`**

Add `RubricStore` to the `from labjury.plugins import (...)` block; add `from labjury.rubrics import InMemoryRubricStore, Rubric`; add `assert_rubric_store_contract` to the `from labjury.testing import (...)` block. Add the four names to `__all__` under a new `# rubric registry` group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS (all prior tests + rubrics + public API).

- [ ] **Step 5: Write `docs/rubric-registry.md` and link it from both READMEs**

`docs/rubric-registry.md`: the problem (inline, unversioned `label → Question`); the `Rubric`/`RubricStore` seam and its four methods; the versioning + immutability model; the example of a proposer sourcing its question (`r = await store.resolve(label); Candidate(label, kind, r.question, rubric_version=r.version)`); the reproducibility link (how `rubric_version` rides into the audit trail, and `get(label, version)` as the read that reconstructs the exact rubric a past decision used); bring-your-own-backend (the conformance suite + the deferred durable variant, consistent with `docs/taxonomy-backends.md`); and the Non-goals (no engine auto-wiring, no built-in rubrics, no content judgment). Add a "### Rubric registry (opt-in)" section to `README.md` and "### Sổ đăng ký rubric (tùy chọn)" to `README.vi.md`, each linking `docs/rubric-registry.md`, placed after the security sections.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/rubric-registry.md README.md README.vi.md
git commit -m "feat: re-export rubric registry surface; docs + bring-your-own-backend"
```
