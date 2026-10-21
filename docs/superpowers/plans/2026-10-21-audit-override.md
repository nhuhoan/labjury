# Audit the human override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `labjury.review.override_event(event, resolution) -> AuditEvent` — the inverse of `review_task_from_event`: record a human override as a new immutable, correlation-linked `AuditEvent` with reviewer provenance; no core/contract change.

**Architecture:** A pure function in `labjury.review` (already the bridge between review types and `AuditEvent`). It carries forward the original event's inputs, sets the verdict to the human resolution's, and attributes the event to the reviewer only. The deployer appends the result to their own `AuditLog`.

**Tech Stack:** Python 3.11+ stdlib; pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-10-21-audit-override-design.md`

## Global Constraints

- Pure core, `dependencies = []`; lives in `labjury.review`; no engine/contract change, no new type.
- Links by `correlation_id`; mismatch raises `ValueError`. Reviewer-only provenance (machine provenance NOT merged).
- Re-exported top-level (`override_event`) — additive to `__all__`.
- TDD throughout; commit per task.

## Review Focus

- `correlation_id` mismatch → `ValueError` — Task 1 (`test_correlation_mismatch_raises`).
- `verdict` == resolution `to_verdict()` serialized — Task 1 (`test_verdict_is_human_decision`).
- `provenance["reviewer"]` has reviewer name + note/decided_at params; machine provenance absent — Task 1 (`test_reviewer_provenance`).
- Inputs carried forward from original — Task 1 (`test_inputs_carried_forward`).
- Fresh `event_id`; round-trips through `to_dict`/`from_dict` — Task 1 (`test_fresh_event_id`, `test_roundtrips`).

---

### Task 1: `override_event`

**Files:**
- Modify: `src/labjury/review.py` (add `override_event`; import `ProvenanceRef`, `verdict_to_dict`)
- Modify: `src/labjury/__init__.py` (re-export `override_event`; add to `__all__`)
- Test: `tests/test_review.py` (add override-event cases)

**Interfaces:**
- Consumes: `AuditEvent` (fields `correlation_id`, `input_fingerprint`, `modalities`, `candidates`, `answers`, `known_labels`, `tenant`); `ReviewResolution` (`correlation_id`, `reviewer`, `note`, `decided_at`, `to_verdict()`); `ProvenanceRef`, `verdict_to_dict` from `labjury.audit`.
- Produces: `labjury.review.override_event(event: AuditEvent, resolution: ReviewResolution) -> AuditEvent`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review.py`

```python
def _orig():
    from labjury.audit import AuditEvent
    return AuditEvent(
        "c1", "fp123",
        modalities=frozenset({"text"}),
        candidates=({"label": "nsfw"},),
        answers=({"q": "a"},),
        known_labels=frozenset({"nsfw"}),
        verdict={"action": "review", "labels": [], "scores": {}, "novel_labels": [], "reason": "borderline"},
        tenant="acme",
    )


def _res(correlation_id="c1"):
    from labjury.review import ReviewResolution
    return ReviewResolution(correlation_id, "block", ["nsfw"], "alice", note="confirmed", decided_at="2026-10-21T00:00:00+00:00")


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_review.py -k override -v` (and `test_roundtrips`/`test_fresh_event_id`/`test_inputs_carried_forward`/`test_reviewer_provenance`/`test_verdict_is_human_decision`/`test_correlation_mismatch_raises`)
Expected: FAIL — `cannot import name 'override_event'`.

- [ ] **Step 3: Implement `override_event` in `src/labjury/review.py`**

Import `ProvenanceRef`, `verdict_to_dict` from `labjury.audit` (alongside the existing `AuditEvent` import). Raise `ValueError` if `resolution.correlation_id != event.correlation_id`. Return a new `AuditEvent` with: `correlation_id`, `input_fingerprint`, `modalities`, `candidates`, `answers`, `known_labels`, `tenant` copied from `event`; `verdict=verdict_to_dict(resolution.to_verdict())`; `provenance={"reviewer": ProvenanceRef(resolution.reviewer, None, {"note": resolution.note, "decided_at": resolution.decided_at})}`. Let `event_id`/`occurred_at` default (fresh). `used_proposer`/`from_cache` default.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_review.py -v`
Expected: PASS (new cases + existing).

- [ ] **Step 5: Re-export** — add `override_event` to the `labjury.review` import block and the `# human review` group of `__all__` in `src/labjury/__init__.py`.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS; `PYTHONPATH=src python -c "import labjury; labjury.override_event"`.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/review.py src/labjury/__init__.py tests/test_review.py
git commit -m "feat: override_event — record a human review override as an audit event"
```

---

### Task 2: Docs

**Files:**
- Modify: `docs/human-review.md` (add an "Auditing the override" subsection)
- Modify: `README.md`, `README.vi.md` (one-line pointer in the human-review area)

**Interfaces:**
- Consumes: `override_event` (Task 1).

- [ ] **Step 1: Document in `docs/human-review.md`**

An "Auditing the override" subsection: the round-trip (`review_task_from_event` out → human decides → `override_event(event, resolution)` back), what the event records (correlation link, carried-forward inputs, human verdict, reviewer-only provenance), that it's a distinct append-only event the deployer writes to their `AuditLog`, and the `correlation_id` guard. Show the call.

- [ ] **Step 2: README pointers**

In the human-review area of `README.md`, add a sentence that a human override can be recorded back to the audit trail via `lj.override_event`; mirror in `README.vi.md`.

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS (docs-only).

- [ ] **Step 4: Commit**

```bash
git add docs/human-review.md README.md README.vi.md
git commit -m "docs: auditing the human override in human-review + README pointers"
```
