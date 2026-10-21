# Metered scorer — token/$ cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `labjury.cost` — `CostMeter` (a zero-dep side-channel token accumulator a deployer's scorer reports into) + `TokenUsage` (frozen value with `total_tokens` and a `cost(rates)` helper); no engine/contract change.

**Architecture:** Token cost originates inside the scorer, which the `Observer` hooks can't see; rather than break the `Scorer`/`Observer`/`ItemResult` contract, the scorer reports into an injected `CostMeter`. The meter accumulates per tenant (untagged = `None` bucket); `TokenUsage.cost(in_per_1k, out_per_1k)` does the tokens×rate arithmetic over deployer-supplied rates. Mirrors `PerTenantUsage` in shape (`for_tenant`/`snapshot`).

**Tech Stack:** Python 3.11+ stdlib; pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-metered-cost-design.md`

## Global Constraints

- Zero-dep, lives in the package proper (`labjury.cost`), not `contrib`.
- No engine wiring, no `Scorer`/`Observer`/`ItemResult` change; the meter is a DI side channel.
- The framework owns counting + the multiply; the deployer owns the rate and the reporting.
- Re-exported top-level (`CostMeter`, `TokenUsage`) — additive to `__all__`.
- TDD throughout; commit per task.

## Review Focus

- `record` accumulates in/out/calls per tenant across calls — Task 1 (`test_record_accumulates`).
- `for_tenant` unseen → zero `TokenUsage`, no insert — Task 1 (`test_for_tenant_unseen`).
- `total()` sums across tenants incl. `None` — Task 1 (`test_total_aggregates`).
- `snapshot()` is a copy; mutating it doesn't change the meter — Task 1 (`test_snapshot_is_copy`).
- `TokenUsage.cost`/`total_tokens`; zero usage → `0.0` — Task 1 (`test_cost_arithmetic`).
- Untagged (`None`) bucket tracked — Task 1 (`test_untagged_bucket`).

---

### Task 1: `labjury.cost` — `TokenUsage` + `CostMeter`

**Files:**
- Create: `src/labjury/cost.py`
- Modify: `src/labjury/__init__.py` (re-export `CostMeter`, `TokenUsage`; add to `__all__`)
- Test: `tests/test_cost.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `labjury.cost.TokenUsage` — frozen dataclass `tokens_in: int = 0`, `tokens_out: int = 0`, `calls: int = 0`; property `total_tokens -> int`; method `cost(in_per_1k: float, out_per_1k: float) -> float`.
  - `labjury.cost.CostMeter` — `record(tokens_in=0, tokens_out=0, *, tenant=None) -> None`; `for_tenant(tenant) -> TokenUsage`; `total() -> TokenUsage`; `snapshot() -> dict[str | None, TokenUsage]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_cost.py`

```python
from labjury.cost import CostMeter, TokenUsage


def test_record_accumulates():
    m = CostMeter()
    m.record(tokens_in=100, tokens_out=20, tenant="acme")
    m.record(tokens_in=50, tokens_out=10, tenant="acme")
    u = m.for_tenant("acme")
    assert (u.tokens_in, u.tokens_out, u.calls) == (150, 30, 2)


def test_for_tenant_unseen():
    m = CostMeter()
    u = m.for_tenant("nobody")
    assert (u.tokens_in, u.tokens_out, u.calls) == (0, 0, 0)
    assert m.snapshot() == {}          # for_tenant did not insert


def test_total_aggregates():
    m = CostMeter()
    m.record(tokens_in=100, tokens_out=20, tenant="a")
    m.record(tokens_in=5, tokens_out=1)            # untagged
    t = m.total()
    assert (t.tokens_in, t.tokens_out, t.calls) == (105, 21, 2)


def test_snapshot_is_copy():
    m = CostMeter()
    m.record(tokens_in=1, tokens_out=1, tenant="a")
    snap = m.snapshot()
    snap.clear()
    assert "a" in m.snapshot()         # mutating the copy didn't touch the meter


def test_cost_arithmetic():
    u = TokenUsage(tokens_in=2000, tokens_out=1000)
    assert u.total_tokens == 3000
    assert u.cost(in_per_1k=0.25, out_per_1k=1.25) == 2000 / 1000 * 0.25 + 1000 / 1000 * 1.25
    assert TokenUsage().cost(1.0, 1.0) == 0.0


def test_untagged_bucket():
    m = CostMeter()
    m.record(tokens_in=7, tokens_out=3)
    assert m.for_tenant(None).tokens_in == 7
    assert None in m.snapshot()
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_cost.py -v`
Expected: FAIL — `No module named 'labjury.cost'`.

- [ ] **Step 3: Implement `src/labjury/cost.py`**

`TokenUsage` frozen dataclass per Interfaces (`total_tokens` property; `cost` = `tokens_in / 1000 * in_per_1k + tokens_out / 1000 * out_per_1k`). `CostMeter` holds `dict[str | None, list[int]]` (`[in, out, calls]`); `record` does `bucket = self._by.setdefault(tenant, [0, 0, 0]); bucket[0] += tokens_in; bucket[1] += tokens_out; bucket[2] += 1`; `for_tenant` builds a `TokenUsage` from the bucket or returns `TokenUsage()` without inserting; `total` sums all buckets into one `TokenUsage`; `snapshot` returns `{t: TokenUsage(*b) for t, b in self._by.items()}` (fresh dict of fresh frozen values). Module docstring: side-channel meter, scorer reports in, deployer owns the rate.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_cost.py -v`
Expected: PASS.

- [ ] **Step 5: Re-export** — add `CostMeter`, `TokenUsage` to a new `labjury.cost` import in `src/labjury/__init__.py` and a `# cost metering` group in `__all__`.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS; `PYTHONPATH=src python -c "import labjury; labjury.CostMeter; labjury.TokenUsage"`.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/cost.py src/labjury/__init__.py tests/test_cost.py
git commit -m "feat: CostMeter + TokenUsage — side-channel scorer token/cost metering"
```

---

### Task 2: Docs

**Files:**
- Create: `docs/cost-metering.md`
- Modify: `README.md`, `README.vi.md` (one-line pointer in the observability/cost area)

**Interfaces:**
- Consumes: `CostMeter`, `TokenUsage` (Task 1).

- [ ] **Step 1: Write `docs/cost-metering.md`**

Why a side channel (tokens originate in the scorer, the `Observer` hooks + `ItemResult` can't carry them, and the contract isn't changing); the deployer wires a `CostMeter` into their scorer and calls `record(...)` per model call (show the snippet from the spec); `for_tenant`/`total`/`snapshot`; `TokenUsage.cost(in_per_1k, out_per_1k)` with the rate as the deployer's pricing input; how it complements `PerTenantUsage` (counts+latency there, tokens+$ here, both keyed by tenant); and the non-goals (no price table, no engine wiring, single-event-loop).

- [ ] **Step 2: README pointers**

In the observability/cost area of `README.md`, add a sentence that token/$ cost is metered via `lj.CostMeter` (scorer reports in; `TokenUsage.cost(rates)` for $); mirror in `README.vi.md`.

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS (docs-only).

- [ ] **Step 4: Commit**

```bash
git add docs/cost-metering.md README.md README.vi.md
git commit -m "docs: cost metering — CostMeter side channel + bring-your-own pricing"
```
