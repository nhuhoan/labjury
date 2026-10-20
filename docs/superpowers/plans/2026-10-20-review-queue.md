# Human Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the stateless, fire-and-forget human-review contract — portable `ReviewTask`/`ReviewResolution` value objects (with a builder from an `AuditEvent` and a `to_verdict` back-conversion) and a `ReviewQueue` protocol with a zero-dep `InMemoryReviewQueue` — without changing the engine.

**Architecture:** `labjury.review` holds the value objects and the in-memory queue; `labjury.plugins` holds the one-method `ReviewQueue` protocol. The review package *is* the audit package: `review_task_from_event` reads an `AuditEvent`'s candidates/answers/verdict/tenant. A human decision (`ReviewResolution`) converts to a final `Verdict` via `to_verdict`. The engine is untouched — wiring REVIEW results to a queue and feeding decisions back is deployer orchestration, which is what the fire-and-forget contract keeps out of core. Zero new dependency.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`, `datetime`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-review-queue-design.md`

## Global Constraints

- Core `dependencies = []`; stdlib only; mechanism in `labjury.review` + protocol in `labjury.plugins`. Core never imports `labjury.contrib`.
- No engine change, no auto-enqueue, no consumer loop/ack/assignment/SLA.
- No conformance suite for `ReviewQueue` — one fire-and-forget method, the `@runtime_checkable` protocol is the check (same ruling as `Observer`).
- Value objects JSON-serializable via `to_dict`/`from_dict`; `from_dict` tolerates missing optional keys.
- No plugin contract change; additions are new types / a new protocol.
- TDD throughout; commit per task.

## Review Focus

- `review_task_from_event` carries candidates/answers/verdict/tenant/correlation — pinned in Task 1 (`test_review_task_from_event`).
- `ReviewTask`/`ReviewResolution` round-trip and tolerate missing optional keys — pinned in Task 1 (`test_review_task_roundtrip`, `test_resolution_roundtrip`, `test_from_dict_tolerates_missing_optionals`).
- `to_verdict` maps action→enum, keeps labels, empties scores, sets reason; unknown action raises — pinned in Task 1 (`test_resolution_to_verdict`, `test_resolution_unknown_action_raises`).
- `enqueue` is fire-and-forget (`None`); `pending` reflects order; `drain` empties — pinned in Task 2 (`test_enqueue_and_drain`).
- `pending`/`drain` return copies — pinned in Task 2 (`test_pending_is_a_copy`).

---

### Task 1: `ReviewTask` + `ReviewResolution` + `review_task_from_event`

**Files:**
- Create: `src/labjury/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `AuditEvent` from `labjury.audit`; `Action`, `Verdict` from `labjury.results`.
- Produces:
  - `labjury.review.ReviewTask` — frozen dataclass: `correlation_id: str`, `candidates: tuple[dict, ...] = ()`, `answers: tuple[dict, ...] = ()`, `tentative_verdict: dict | None = None`, `tenant: str | None = None`, `created_at: str` (ISO default). `to_dict()` / `from_dict(d)`.
  - `labjury.review.ReviewResolution` — frozen dataclass: `correlation_id: str`, `action: str`, `labels: list[str]`, `reviewer: str`, `note: str = ""`, `decided_at: str` (ISO default). `to_dict()` / `from_dict(d)`; `to_verdict() -> Verdict` = `Verdict(Action(self.action), list(self.labels), {}, [], self.note or f"human review by {self.reviewer}")`.
  - `labjury.review.review_task_from_event(event: AuditEvent) -> ReviewTask` — `ReviewTask(event.correlation_id, tuple(event.candidates), tuple(event.answers), event.verdict, event.tenant)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review.py`

```python
import pytest
from labjury.audit import AuditEvent
from labjury.results import Action
from labjury.review import ReviewResolution, ReviewTask, review_task_from_event


def test_review_task_from_event():
    event = AuditEvent("c1", "fp",
        candidates=({"label": "x", "kind": "tag", "question": {}, "rubric_version": None},),
        answers=({"key": "x", "value": True, "confidence": 0.5, "distribution": None},),
        verdict={"action": "review", "labels": [], "scores": {}, "novel_labels": [], "reason": "unsure"},
        tenant="acme")
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
    r = ReviewResolution.from_dict({"correlation_id": "c1", "action": "accept", "labels": [], "reviewer": "bob"})
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_review.py -v`
Expected: FAIL — `No module named 'labjury.review'`.

- [ ] **Step 3: Implement `src/labjury/review.py`**

A local `_now_iso()` (UTC ISO, like `audit.py`). `ReviewTask` and `ReviewResolution` frozen dataclasses per Interfaces, each with `to_dict` (plain dict of fields; `candidates`/`answers` as lists) and a classmethod `from_dict` using `d.get(...)` with defaults for the optional keys (`from_dict` rebuilds `candidates`/`answers` as tuples). `ReviewResolution.to_verdict` as specified. `review_task_from_event` as specified. (`ReviewTask.from_dict` must coerce the `candidates`/`answers` lists back to tuples so round-trip equality holds against a tuple-constructed task.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/labjury/review.py tests/test_review.py
git commit -m "feat: ReviewTask/ReviewResolution value objects + review_task_from_event"
```

---

### Task 2: `ReviewQueue` protocol + `InMemoryReviewQueue`

**Files:**
- Modify: `src/labjury/plugins.py` (add `ReviewQueue` protocol)
- Modify: `src/labjury/review.py` (add `InMemoryReviewQueue`)
- Test: `tests/test_review.py` (add cases)

**Interfaces:**
- Consumes: `ReviewTask` (Task 1).
- Produces:
  - `labjury.plugins.ReviewQueue` — `@runtime_checkable` Protocol: `async def enqueue(self, task: ReviewTask) -> None`.
  - `labjury.review.InMemoryReviewQueue()` — `async def enqueue(self, task) -> None` (appends); `pending() -> list[ReviewTask]` (a copy); `drain() -> list[ReviewTask]` (a copy, then clears).

- [ ] **Step 1: Write the failing tests** in `tests/test_review.py`

```python
from labjury.plugins import ReviewQueue
from labjury.review import InMemoryReviewQueue


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_review.py -k "enqueue or pending_is_a_copy or is_a_review_queue" -v`
Expected: FAIL — `cannot import name 'ReviewQueue'` / `'InMemoryReviewQueue'`.

- [ ] **Step 3: Add the `ReviewQueue` protocol to `src/labjury/plugins.py`**

A `@runtime_checkable` Protocol with `async def enqueue(self, task: "ReviewTask") -> None: ...`, beside the other protocols. Add a `TYPE_CHECKING` import of `ReviewTask` from `labjury.review` (mirror the `Rubric` pattern) and a short docstring: fire-and-forget hand-off; LabJury enqueues and forgets, never pulls or acks.

- [ ] **Step 4: Implement `InMemoryReviewQueue` in `src/labjury/review.py`**

Holds `self._tasks: list[ReviewTask]`. `enqueue` appends and returns `None`. `pending` returns `list(self._tasks)`. `drain` returns `list(self._tasks)` then clears.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_review.py -v`
Expected: PASS (whole file).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/plugins.py src/labjury/review.py tests/test_review.py
git commit -m "feat: ReviewQueue protocol + InMemoryReviewQueue (fire-and-forget)"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/human-review.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `ReviewQueue` (Task 2, from `labjury.plugins`); `ReviewTask`, `ReviewResolution`, `InMemoryReviewQueue`, `review_task_from_event` (Tasks 1–2, from `labjury.review`).
- Produces: the five names importable as `labjury.<name>`.

- [ ] **Step 1: Add the five names to `tests/test_public_api.py`**

Append `"ReviewTask"`, `"ReviewResolution"`, `"ReviewQueue"`, `"InMemoryReviewQueue"`, `"review_task_from_event"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: ReviewTask`.

- [ ] **Step 3: Re-export in `src/labjury/__init__.py`**

Add `ReviewQueue` to the `from labjury.plugins import (...)` block; add `from labjury.review import (InMemoryReviewQueue, ReviewResolution, ReviewTask, review_task_from_event)`; add the five names to `__all__` under a new `# human review` group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Write `docs/human-review.md` and link it**

`docs/human-review.md`: the stateless fire-and-forget framing (LabJury owns the contract, the deployer owns the queue and the workflow); the end-to-end flow the deployer wires — a `Status.REVIEW` result → read its `AuditEvent` → `review_task_from_event` → `queue.enqueue(task)` (fire-and-forget) → human decides in the deployer's tool → `ReviewResolution` → `.to_verdict()` as the final verdict; the `ReviewQueue` seam with the in-memory reference and a note that durable backends (SQS/DB/Pub-Sub) implement the one `enqueue`; recording the override in the audit trail as a documented extension (build an `AuditEvent` from the task + the resolution's verdict with a reviewer provenance); and the Non-goals (no engine auto-enqueue, no consumer loop/ack/assignment/SLA, no queue storage). Add "### Human-in-the-loop review (opt-in)" to `README.md` and "### Review bởi người (tùy chọn)" to `README.vi.md` after the multi-tenancy section, each linking the doc.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/human-review.md README.md README.vi.md
git commit -m "feat: re-export human-review surface; docs"
```
