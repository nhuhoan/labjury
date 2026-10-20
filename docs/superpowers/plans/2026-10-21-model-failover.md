# Model Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `FailoverScorer` / `FailoverProposer` / `FailoverContextBuilder` to the resilience family — zero-dep wrappers that try an ordered list of interchangeable same-kind plugins until one succeeds — re-exported and documented, with no engine change.

**Architecture:** A module-level `_failover(members, call)` helper in `labjury.reliability` loops members in order, returns the first non-raising result, catches `Exception` (not `BaseException`), and re-raises the last exception when all fail. The three wrappers hold a non-empty member list, copy `accepts` (and `produces` for the builder) from the first member, and delegate their one async method through `_failover`. Composes with `Reliable*` (a member can be a `ReliableScorer`).

**Tech Stack:** Python 3.11+, stdlib only, pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-model-failover-design.md`

## Global Constraints

- Core `dependencies = []`; zero-dep mechanism in `labjury.reliability`; re-exported top-level. Core never imports contrib.
- Catch `Exception`, not `BaseException` (CancelledError propagates) — consistent with `Reliable*`.
- Empty member list → `ValueError`. `accepts`/`produces` delegate from the first member.
- No engine change, no plugin-contract change, sequential (no hedging/racing).
- TDD throughout; commit per task.

## Review Focus

- First member succeeds → returned, later members not called — pinned in Task 1 (`test_first_success_short_circuits`).
- Primary raises → fallback used, in order — pinned in Task 1 (`test_failover_to_next_on_error`).
- All raise → last exception propagates — pinned in Task 1 (`test_all_fail_raises_last`).
- `CancelledError` propagates (no failover) — pinned in Task 1 (`test_cancelled_propagates`).
- Empty → `ValueError`; `accepts`/`produces` delegate; isinstance of the protocol — pinned in Task 1.

---

### Task 1: `Failover*` wrappers

**Files:**
- Modify: `src/labjury/reliability.py` (add `_failover` + the three wrappers)
- Test: `tests/test_reliability.py` (add cases)

**Interfaces:**
- Consumes: `Scorer`/`Proposer`/`ContextBuilder` protocols (duck-typed members).
- Produces:
  - `labjury.reliability.FailoverScorer(scorers)` — attr `accepts = scorers[0].accepts`; `async def score(self, state, questions)`.
  - `labjury.reliability.FailoverProposer(proposers)` — attr `accepts`; `async def propose(self, state, context)`.
  - `labjury.reliability.FailoverContextBuilder(builders)` — attrs `accepts`, `produces`; `async def build(self, item, state)`.
  - Each raises `ValueError` on an empty list; each tries members in order, returns the first non-raising result, catches `Exception`, re-raises the last on total failure.

- [ ] **Step 1: Write the failing tests** in `tests/test_reliability.py`

```python
from labjury.reliability import (
    FailoverContextBuilder, FailoverProposer, FailoverScorer,
)
from labjury.plugins import ContextBuilder, Proposer, Scorer


class _OKScorer:
    accepts = frozenset({"text"})
    def __init__(self, tag): self.tag = tag; self.called = False
    async def score(self, state, questions):
        self.called = True
        return [self.tag]

class _BoomScorer:
    accepts = frozenset({"text"})
    def __init__(self): self.called = False
    async def score(self, state, questions):
        self.called = True
        raise RuntimeError("down")

class _CancelScorer:
    accepts = frozenset({"text"})
    async def score(self, state, questions):
        raise __import__("asyncio").CancelledError()


async def test_first_success_short_circuits():
    first, second = _OKScorer("a"), _OKScorer("b")
    out = await FailoverScorer([first, second]).score(None, [])
    assert out == ["a"]
    assert second.called is False

async def test_failover_to_next_on_error():
    primary, backup = _BoomScorer(), _OKScorer("b")
    out = await FailoverScorer([primary, backup]).score(None, [])
    assert out == ["b"]
    assert primary.called is True

async def test_all_fail_raises_last():
    import pytest
    with pytest.raises(RuntimeError):
        await FailoverScorer([_BoomScorer(), _BoomScorer()]).score(None, [])

async def test_cancelled_propagates():
    import asyncio, pytest
    with pytest.raises(asyncio.CancelledError):
        await FailoverScorer([_CancelScorer(), _OKScorer("b")]).score(None, [])

def test_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        FailoverScorer([])

def test_delegates_capabilities_and_is_protocol():
    fs = FailoverScorer([_OKScorer("a")])
    assert fs.accepts == frozenset({"text"})
    assert isinstance(fs, Scorer)
```

(Add parallel minimal cases for `FailoverProposer.propose(state, context)` and `FailoverContextBuilder.build(item, state)` — the latter asserting `produces` is delegated and `isinstance(..., ContextBuilder)`. Reuse tiny fakes.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_reliability.py -k Failover -v`
Expected: FAIL — `cannot import name 'FailoverScorer'`.

- [ ] **Step 3: Implement in `src/labjury/reliability.py`**

Add the module-level `async def _failover(members, call)` (loop in order, return first non-raising, `except Exception` continue, re-raise last; `assert last_exc is not None`), then `FailoverScorer`, `FailoverProposer`, `FailoverContextBuilder` per Interfaces (each validates non-empty, copies capability attrs from `members[0]`, delegates via `_failover`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_reliability.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/labjury/reliability.py tests/test_reliability.py
git commit -m "feat: Failover{Scorer,Proposer,ContextBuilder} — primary->fallback resilience"
```

---

### Task 2: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Modify: `docs/reliability.md`, `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: the three `Failover*` (Task 1, from `labjury.reliability`).
- Produces: the three names importable as `labjury.<name>`.

- [ ] **Step 1: Add the three names to `tests/test_public_api.py`**

Append `"FailoverScorer"`, `"FailoverProposer"`, `"FailoverContextBuilder"` to the list the suite checks.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `FailoverScorer in __all__ but not importable` (after adding to `__all__`) / missing export.

- [ ] **Step 3: Re-export in `src/labjury/__init__.py`**

Add the three to the `from labjury.reliability import (...)` block and to `__all__` under the remote-plugin reliability group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Document**

Extend `docs/reliability.md` with a "Failover across models" section: the three wrappers, the empty-list/all-fail/CancelledError semantics, and the composition `FailoverScorer([ReliableScorer(primary), ReliableScorer(backup)])`. Add a short bilingual note to the existing reliability README sections pointing at failover.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/reliability.md README.md README.vi.md
git commit -m "feat: re-export Failover wrappers; document failover composition"
```
