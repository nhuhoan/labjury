# Remote-Plugin Reliability Standard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a model-agnostic reliability standard — `ReliableScorer` /
`ReliableProposer` / `ReliableContextBuilder` wrappers applying timeout → retry →
circuit-breaker to any remote plugin.

**Architecture:** A single internal runner holds the config and breaker state and
runs any awaitable-factory through `breaker(retry(timeout(call)))`, re-raising on
exhaustion. Three thin wrappers each own a runner, delegate their capability
attributes, and route their one protocol method through it. Zero dependency,
pure `asyncio`; a wrapper that gives up raises, and the engine's existing
partial-failure path turns that into `ItemResult(FAILED)` — no engine change.

**Tech Stack:** stdlib `asyncio`, `time.monotonic`.

**Spec:** `docs/superpowers/specs/2026-10-20-remote-plugin-reliability-design.md`

## Global Constraints

- Zero new dependency; lives in core `src/labjury/reliability.py`; the core
  imports no HTTP/model library and no `labjury.contrib`.
- The wrappers are opt-in composition — they must not change any existing plugin
  or require an engine change.
- Each wrapper satisfies the protocol it wraps (`isinstance` is `True`) and
  delegates capability attributes: `accepts` for all three, plus `produces` for
  `ReliableContextBuilder`.
- Config knobs, same on all three wrappers, with these defaults: `timeout_s=5.0`
  (`None` disables), `retries=2` (`0` disables), `backoff_base_s=0.1`,
  `backoff_max_s=2.0`, `failure_threshold=5` (`<=0` disables the breaker),
  `reset_timeout_s=30.0`, `clock=time.monotonic`.
- Composition order is `breaker(retry(timeout(call)))`: the timeout bounds **each
  attempt**; `CircuitOpenError` is raised when the breaker is open.
- Re-exported from top-level `labjury`: `ReliableScorer`, `ReliableProposer`,
  `ReliableContextBuilder`, `CircuitOpenError`.

## Review Focus

- **Timeout bounds each attempt, not the whole budget**: a hanging call with
  `retries>0` must still raise `TimeoutError` (each attempt times out), never
  block forever — pinned in Task 1.
- **Open breaker fast-fails without calling the inner plugin**: once open, a call
  raises `CircuitOpenError` and the inner plugin's call count does not increase —
  pinned in Task 1.
- **Half-open closes on a success** after the clock passes `reset_timeout_s` —
  pinned in Task 1 (injected clock).
- **Disabled knobs are honored**: `failure_threshold<=0` never raises
  `CircuitOpenError`; `timeout_s=None` never times out; `retries=0` makes exactly
  one attempt — pinned in Task 1.
- **`ReliableContextBuilder` delegates `produces`, not only `accepts`** — pinned
  in Task 2.

---

### Task 1: Reliability runner + `ReliableScorer`

**Files:**
- Create: `src/labjury/reliability.py`
- Test: `tests/test_reliability.py`

**Interfaces:**
- Consumes: `labjury.plugins.Scorer`; `labjury.decisions.Answer`,
  `ChoiceQuestion`; `labjury.state.State`.
- Produces: `CircuitOpenError(Exception)`; an internal runner applying
  `breaker(retry(timeout(call)))`; `ReliableScorer(inner, *, timeout_s=5.0,
  retries=2, backoff_base_s=0.1, backoff_max_s=2.0, failure_threshold=5,
  reset_timeout_s=30.0, clock=time.monotonic)` → satisfies `Scorer`, with
  `accepts = inner.accepts` and `async def score(self, state, questions)`.

- [ ] **Step 1: Write the failing tests**

```python
import asyncio
import pytest
from labjury.decisions import Answer, ChoiceQuestion
from labjury.plugins import Scorer
from labjury.reliability import CircuitOpenError, ReliableScorer

_Q = [ChoiceQuestion("q", "?", ["x"])]
_OK = [Answer("q", value="x", confidence=1.0)]

class FlakyScorer:
    accepts = frozenset({"*"})
    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times
    async def score(self, state, questions):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return list(_OK)

class HangingScorer:
    accepts = frozenset({"*"})
    def __init__(self):
        self.calls = 0
    async def score(self, state, questions):
        self.calls += 1
        await asyncio.Event().wait()  # never returns

class FakeClock:
    def __init__(self):
        self.t = 0.0
    def now(self):
        return self.t
    def advance(self, dt):
        self.t += dt

async def test_retry_succeeds_after_transient_failures():
    inner = FlakyScorer(fail_times=2)
    rel = ReliableScorer(inner, retries=2, backoff_base_s=0.0, timeout_s=None)
    assert await rel.score(None, _Q) == _OK
    assert inner.calls == 3

async def test_retry_exhausted_reraises():
    inner = FlakyScorer(fail_times=3)
    rel = ReliableScorer(inner, retries=2, backoff_base_s=0.0, timeout_s=None)
    with pytest.raises(RuntimeError):
        await rel.score(None, _Q)

async def test_timeout_applies_per_attempt():
    inner = HangingScorer()
    rel = ReliableScorer(inner, timeout_s=0.01, retries=1, backoff_base_s=0.0,
                         failure_threshold=0)
    with pytest.raises(TimeoutError):
        await rel.score(None, _Q)
    assert inner.calls == 2  # each attempt was bounded and retried once

async def test_breaker_opens_and_fast_fails_without_calling_inner():
    inner = FlakyScorer(fail_times=999)
    rel = ReliableScorer(inner, retries=0, timeout_s=None, failure_threshold=3)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)
    assert inner.calls == 3
    with pytest.raises(CircuitOpenError):
        await rel.score(None, _Q)
    assert inner.calls == 3  # inner not called while open

async def test_breaker_half_open_closes_on_success():
    inner = FlakyScorer(fail_times=2)
    clock = FakeClock()
    rel = ReliableScorer(inner, retries=0, timeout_s=None, failure_threshold=2,
                         reset_timeout_s=10.0, clock=clock.now)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)
    with pytest.raises(CircuitOpenError):
        await rel.score(None, _Q)
    clock.advance(11.0)
    assert await rel.score(None, _Q) == _OK  # half-open trial succeeds -> closed
    assert await rel.score(None, _Q) == _OK

async def test_breaker_disabled_never_opens():
    inner = FlakyScorer(fail_times=999)
    rel = ReliableScorer(inner, retries=0, timeout_s=None, failure_threshold=0)
    for _ in range(10):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)  # RuntimeError, never CircuitOpenError
    assert inner.calls == 10

def test_reliable_scorer_is_a_scorer():
    rel = ReliableScorer(FlakyScorer(0))
    assert isinstance(rel, Scorer) and rel.accepts == frozenset({"*"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_reliability.py -v`
Expected: FAIL — `No module named 'labjury.reliability'`.

- [ ] **Step 3: Implement the runner, `CircuitOpenError`, and `ReliableScorer`**

In `src/labjury/reliability.py`:
- `class CircuitOpenError(Exception)`.
- An internal runner (e.g. `_Reliable`) built from the config kwargs, holding
  breaker state (`consecutive_failures`, `opened_at`), with
  `async def run(self, make_awaitable: Callable[[], Awaitable[T]]) -> T`:
  - **breaker gate (if `failure_threshold > 0`):** if open and
    `clock() - opened_at < reset_timeout_s`, raise `CircuitOpenError` without
    calling; if open and the window passed, allow one half-open trial.
  - **attempt loop:** for up to `retries + 1` attempts, create a fresh awaitable
    via `make_awaitable()` and await it under `asyncio.wait_for(aw, timeout_s)`
    when `timeout_s is not None` (else await directly); on success record a
    breaker success (reset failures, close) and return; on `except Exception`
    (NOT `BaseException` — `asyncio.CancelledError` must propagate, never be
    retried) record a breaker failure, and if attempts remain `await
    asyncio.sleep(min(backoff_base_s * 2**attempt, backoff_max_s))` and continue,
    else re-raise.
  - A breaker failure that reaches `failure_threshold` sets open + `opened_at =
    clock()`.
- `ReliableScorer(inner, *, <config kwargs with the spec defaults>)`: store
  `inner`, set `self.accepts = inner.accepts`, build one runner;
  `async def score(self, state, questions)` returns
  `await self._runner.run(lambda: inner.score(state, questions))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_reliability.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass (prior 84 + 7), 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/reliability.py tests/test_reliability.py
git commit -m "feat: reliability runner + ReliableScorer (timeout/retry/circuit-breaker)"
```

---

### Task 2: `ReliableProposer`, `ReliableContextBuilder`, and public API

**Files:**
- Modify: `src/labjury/reliability.py` (add two wrappers)
- Modify: `src/labjury/__init__.py` (re-export the four names)
- Test: `tests/test_reliability.py`, `tests/test_public_api.py`

**Interfaces:**
- Consumes: the runner from Task 1; `labjury.plugins.Proposer`,
  `ContextBuilder`, `ProposalContext`; `labjury.decisions.Candidate`,
  `ChoiceQuestion`; `labjury.state.State`, `Item`.
- Produces: `ReliableProposer(inner, *, <same config kwargs>)` → `Proposer`,
  `accepts = inner.accepts`, `async def propose(self, state, context)`;
  `ReliableContextBuilder(inner, *, <same config kwargs>)` → `ContextBuilder`,
  `accepts = inner.accepts`, `produces = inner.produces`,
  `async def build(self, item, state)`.

- [ ] **Step 1: Write the failing tests**

```python
from labjury.plugins import ContextBuilder, Proposer, ProposalContext
from labjury.decisions import Candidate
from labjury.reliability import ReliableContextBuilder, ReliableProposer

class FlakyProposer:
    accepts = frozenset({"*"})
    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times
    async def propose(self, state, context):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return [Candidate("food", "tag", ChoiceQuestion("q", "?", ["food"]))]

class FlakyBuilder:
    accepts = frozenset({"text"})
    produces = frozenset({"json"})
    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times
    async def build(self, item, state):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return state

async def test_reliable_proposer_retries_and_is_a_proposer():
    inner = FlakyProposer(fail_times=1)
    rel = ReliableProposer(inner, retries=1, backoff_base_s=0.0, timeout_s=None)
    out = await rel.propose(None, ProposalContext())
    assert out and inner.calls == 2
    assert isinstance(rel, Proposer) and rel.accepts == frozenset({"*"})

async def test_reliable_context_builder_delegates_accepts_and_produces():
    inner = FlakyBuilder(fail_times=1)
    rel = ReliableContextBuilder(inner, retries=1, backoff_base_s=0.0, timeout_s=None)
    state = object()
    assert await rel.build(None, state) is state and inner.calls == 2
    assert isinstance(rel, ContextBuilder)
    assert rel.accepts == frozenset({"text"}) and rel.produces == frozenset({"json"})
```

Add to `tests/test_public_api.py` an assertion that `labjury.ReliableScorer`,
`labjury.ReliableProposer`, `labjury.ReliableContextBuilder`, and
`labjury.CircuitOpenError` are importable from the top-level package.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_reliability.py tests/test_public_api.py -v`
Expected: FAIL — `ReliableProposer` / `ReliableContextBuilder` not defined; the
top-level names not importable.

- [ ] **Step 3: Implement the two wrappers and the re-exports**

- In `src/labjury/reliability.py`, add `ReliableProposer` and
  `ReliableContextBuilder` mirroring `ReliableScorer`: store `inner`, build a
  runner, delegate `accepts` (and `produces` for the builder), and route the one
  method (`propose(state, context)` / `build(item, state)`) through
  `self._runner.run(lambda: ...)`.
- In `src/labjury/__init__.py`, import and add to `__all__`: `ReliableScorer`,
  `ReliableProposer`, `ReliableContextBuilder`, `CircuitOpenError`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_reliability.py tests/test_public_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass; 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/reliability.py src/labjury/__init__.py tests/test_reliability.py tests/test_public_api.py
git commit -m "feat: ReliableProposer, ReliableContextBuilder, public API"
```

---

### Task 3: Documentation

**Files:**
- Create: `docs/reliability.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: the four public names from Task 2.
- Produces: nothing code depends on.

- [ ] **Step 1: Write `docs/reliability.md`**

Cover: the standard is model-agnostic (wraps any `Scorer`/`Proposer`/
`ContextBuilder`, nothing Jev-specific); the three behaviors and their knobs with
defaults; the `breaker(retry(timeout(call)))` order (timeout per attempt); that
wrapped methods must be **read-only/idempotent** (retry safety); that a give-up
surfaces as an `ItemResult(FAILED)` through the engine for the caller to
re-enqueue; a usage example `Engine(..., scorers=[ReliableScorer(JevScorer(...),
timeout_s=2.0)])`; and that failover across several same-kind models is the
sibling composition, not this step.

- [ ] **Step 2: Add one-line pointers to `README.md` and `README.vi.md`**

In each, a sentence that remote plugins can be wrapped for reliability
(`labjury.ReliableScorer` / `ReliableProposer` / `ReliableContextBuilder`,
timeout/retry/circuit-breaker, zero-dep) linking `docs/reliability.md`.

- [ ] **Step 3: Verify the documented imports**

Run: `python -c "import labjury as lj; lj.ReliableScorer; lj.ReliableProposer; lj.ReliableContextBuilder; lj.CircuitOpenError"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add docs/reliability.md README.md README.vi.md
git commit -m "docs: remote-plugin reliability standard"
```
