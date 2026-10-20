# Multi-tenancy (attribution + per-tenant usage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread an optional tenant identity through `Item → ItemResult → AuditEvent` so every decision is attributable, and ship a zero-dep `PerTenantUsage` observer (plus a `FanOutObserver` to run it beside existing observers) that tallies decision counts and latency per tenant.

**Architecture:** `tenant: str | None = None` is appended as a defaulted field to `Item`, `ItemResult`, and `AuditEvent` (carried through the audit `to_dict`/`from_dict` seam). The engine copies `item.tenant` onto every result and records it on both audit events — it never branches on it. `PerTenantUsage` and `FanOutObserver` are `Observer` implementations in `labjury.observability`; the protocol is unchanged. Per-tenant cost at the framework level is the model-agnostic signal the engine owns (counts + latency); dollar cost is the deployer's. Zero new dependency, pure core.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-multi-tenancy-design.md`

## Global Constraints

- Core `dependencies = []`; stdlib only; mechanisms in core (`state`/`results`/`audit`/`observability`). Core never imports `labjury.contrib`.
- No public plugin contract change. Tenant fields are appended optional defaults; `PerTenantUsage`/`FanOutObserver` are implementations of the unchanged `Observer` protocol.
- The engine threads `item.tenant` onto outputs only — it never reads tenant to make a decision.
- No token/$ cost, no storage partitioning, no rate-limit/quota.
- TDD throughout; commit per task.

## Review Focus

- Tenant flows end-to-end: `Item(tenant="acme")` → `ItemResult.tenant == "acme"` and recorded `AuditEvent.tenant == "acme"` — pinned in Task 1 (`test_tenant_flows_to_result_and_audit`).
- `AuditEvent.tenant` round-trips through `to_dict`/`from_dict`; a dict without the key decodes to `None` — pinned in Task 1 (`test_audit_event_tenant_roundtrip`, `test_audit_event_tenant_defaults_none`).
- A no-tenant result lands in the `None` bucket, separate from a tagged tenant — pinned in Task 2 (`test_untagged_traffic_in_none_bucket`).
- `avg_latency_ms` is `None` with no samples, the mean otherwise; a `retry_later` (latency `None`) adds to the count but no latency — pinned in Task 2 (`test_avg_latency`, `test_retry_later_has_no_latency`).
- `FanOutObserver` forwards every hook to every child in order — pinned in Task 2 (`test_fanout_forwards_all_hooks`).
- `for_tenant` on an unseen tenant returns a zero tally, not `KeyError` — pinned in Task 2 (`test_for_tenant_unseen_is_zero`).

---

### Task 1: Tenant attribution — fields + engine threading

**Files:**
- Modify: `src/labjury/state.py` (`Item.tenant`)
- Modify: `src/labjury/results.py` (`ItemResult.tenant`)
- Modify: `src/labjury/audit.py` (`AuditEvent.tenant` + `to_dict`/`from_dict`)
- Modify: `src/labjury/engine.py` (thread `item.tenant` onto results and audit events)
- Test: `tests/test_engine.py` (end-to-end), `tests/test_audit.py` (round-trip)

**Interfaces:**
- Consumes: existing `Item`, `ItemResult`, `AuditEvent`, `Engine`.
- Produces:
  - `Item.tenant: str | None = None`; `ItemResult.tenant: str | None = None`; `AuditEvent.tenant: str | None = None`.
  - `AuditEvent.to_dict()` includes `"tenant": self.tenant`; `from_dict` reads `d.get("tenant")`.
  - Engine: `process` sets `result.tenant = item.tenant`; `process_batch` sets `.tenant` on its directly-built `RETRY_LATER` and `FAILED` results; `_run` passes `tenant=item.tenant` to both `AuditEvent(...)` calls.

- [ ] **Step 1: Write the failing tests**

In `tests/test_audit.py`:

```python
def test_audit_event_tenant_roundtrip():
    e = AuditEvent("c1", "fp", tenant="acme")
    assert e.to_dict()["tenant"] == "acme"
    assert AuditEvent.from_dict(e.to_dict()).tenant == "acme"

def test_audit_event_tenant_defaults_none():
    d = AuditEvent("c1", "fp").to_dict()
    d.pop("tenant", None)
    assert AuditEvent.from_dict(d).tenant is None
```

In `tests/test_engine.py` (reuse the module's existing engine-building helper/fixtures; an `InMemoryAuditLog` passed as `audit=`):

```python
async def test_tenant_flows_to_result_and_audit():
    audit = InMemoryAuditLog()
    eng = <build engine with audit=audit>          # per this module's existing pattern
    result = await eng.process(Item("i1", {"text": "x"}, tenant="acme"))
    assert result.tenant == "acme"
    events = await audit.by_correlation("i1")
    assert events and events[0].tenant == "acme"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_audit.py -k tenant tests/test_engine.py -k tenant_flows -v`
Expected: FAIL — `Item.__init__() got an unexpected keyword argument 'tenant'` / `KeyError: 'tenant'`.

- [ ] **Step 3: Add the fields**

`src/labjury/state.py`: append `tenant: str | None = None` to `Item`. `src/labjury/results.py`: append `tenant: str | None = None` to `ItemResult`. `src/labjury/audit.py`: add `tenant: str | None = None` to `AuditEvent` (after `verdict`, before the `default_factory` fields `event_id`/`occurred_at`); add `"tenant": self.tenant` to `to_dict`; pass `tenant=d.get("tenant")` in `from_dict`.

- [ ] **Step 4: Thread it in `src/labjury/engine.py`**

In `process`, after `result = ...` (where `latency_ms` is set), add `result.tenant = item.tenant`. In `process_batch`, set `.tenant = item.tenant` on the pre-admission `RETRY_LATER` `ItemResult` and on the gather-exception `FAILED` `ItemResult`. In `_run`, add `tenant=item.tenant` to the cache-hit `AuditEvent` and the full-decision `AuditEvent`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_audit.py tests/test_engine.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: PASS (fields are defaulted; nothing else affected).

- [ ] **Step 7: Commit**

```bash
git add src/labjury/state.py src/labjury/results.py src/labjury/audit.py src/labjury/engine.py tests/
git commit -m "feat: tenant attribution through Item -> ItemResult -> AuditEvent"
```

---

### Task 2: Per-tenant usage meter + observer fan-out

**Files:**
- Modify: `src/labjury/observability.py` (add `TenantUsage`, `PerTenantUsage`, `FanOutObserver`)
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `ItemResult` (with `.tenant`, `.latency_ms`, `.status`) from `labjury.results`; the `Observer` protocol.
- Produces:
  - `labjury.observability.TenantUsage` — dataclass: `decided`, `review`, `failed`, `retry_later` (int, default 0), `total_latency_ms` (float, default 0.0), `latency_count` (int, default 0); property `avg_latency_ms -> float | None`.
  - `labjury.observability.PerTenantUsage` — `Observer`: four hooks bucket by `result.tenant`; `for_tenant(tenant) -> TenantUsage` (zero tally for unseen, no insert, no raise); `snapshot() -> dict[str | None, TenantUsage]` (a shallow copy of the mapping).
  - `labjury.observability.FanOutObserver(observers: Iterable[Observer])` — `Observer`: each hook calls the same hook on every child in order.

- [ ] **Step 1: Write the failing tests** in `tests/test_observability.py`

Use `ItemResult(correlation_id, status, latency_ms=..., tenant=...)` directly. A `_RecordingObserver` fake that appends `(hook_name, result)` for the fan-out test.

```python
def _r(tenant, status, latency=None):
    return ItemResult("c", status, latency_ms=latency, tenant=tenant)

def test_untagged_traffic_in_none_bucket():
    m = PerTenantUsage()
    m.on_decided(_r("acme", Status.DECIDED, 10.0))
    m.on_decided(_r(None, Status.DECIDED, 20.0))
    assert m.for_tenant("acme").decided == 1
    assert m.for_tenant(None).decided == 1

def test_avg_latency():
    m = PerTenantUsage()
    m.on_decided(_r("acme", Status.DECIDED, 10.0))
    m.on_review(_r("acme", Status.REVIEW, 30.0))
    assert m.for_tenant("acme").avg_latency_ms == 20.0

def test_retry_later_has_no_latency():
    m = PerTenantUsage()
    m.on_retry_later(_r("acme", Status.RETRY_LATER, None))
    u = m.for_tenant("acme")
    assert u.retry_later == 1
    assert u.latency_count == 0
    assert u.avg_latency_ms is None

def test_for_tenant_unseen_is_zero():
    m = PerTenantUsage()
    u = m.for_tenant("ghost")
    assert (u.decided, u.review, u.failed, u.retry_later) == (0, 0, 0, 0)
    assert m.snapshot() == {}          # for_tenant did not insert

def test_snapshot_is_isolated():
    m = PerTenantUsage()
    m.on_failed(_r("acme", Status.FAILED, 5.0))
    snap = m.snapshot()
    snap.clear()
    assert m.for_tenant("acme").failed == 1

def test_fanout_forwards_all_hooks():
    a, b = _RecordingObserver(), _RecordingObserver()
    fan = FanOutObserver([a, b])
    r = _r("acme", Status.DECIDED, 1.0)
    fan.on_decided(r); fan.on_review(r); fan.on_failed(r); fan.on_retry_later(r)
    for obs in (a, b):
        assert [h for h, _ in obs.calls] == ["on_decided", "on_review", "on_failed", "on_retry_later"]

def test_meters_are_observers():
    assert isinstance(PerTenantUsage(), Observer)
    assert isinstance(FanOutObserver([]), Observer)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_observability.py -v`
Expected: FAIL — `cannot import name 'PerTenantUsage'`.

- [ ] **Step 3: Implement the three classes in `src/labjury/observability.py`**

`TenantUsage` dataclass with the `avg_latency_ms` property. `PerTenantUsage` holding `dict[str | None, TenantUsage]`: a private `_bump(result, counter_name)` that does `setdefault`, increments the named counter, and when `result.latency_ms is not None` adds to `total_latency_ms` and `latency_count`; the four hooks call `_bump` with their counter. `for_tenant` returns `self._by_tenant.get(tenant) or TenantUsage()` (no insert). `snapshot` returns `dict(self._by_tenant)`. `FanOutObserver` stores `list(observers)` and forwards each hook.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_observability.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/labjury/observability.py tests/test_observability.py
git commit -m "feat: PerTenantUsage meter + FanOutObserver (per-tenant cost signal)"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/multi-tenancy.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `TenantUsage`, `PerTenantUsage`, `FanOutObserver` (Task 2, from `labjury.observability`).
- Produces: the three names importable as `labjury.<name>`.

- [ ] **Step 1: Add the three names to `tests/test_public_api.py`**

Append `"TenantUsage"`, `"PerTenantUsage"`, `"FanOutObserver"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: TenantUsage`.

- [ ] **Step 3: Re-export the names in `src/labjury/__init__.py`**

Add `FanOutObserver`, `PerTenantUsage`, `TenantUsage` to the `from labjury.observability import (...)` block; add the three to `__all__` under a new `# multi-tenancy` group (or the observability group).

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Write `docs/multi-tenancy.md` and link it**

`docs/multi-tenancy.md`: the two needs (attribution, per-tenant cost); the `tenant` field on `Item` and how it flows to `ItemResult` and `AuditEvent` (so deployers partition their stores and filter dashboards by tenant — LabJury carries the identity, the deployer keys their storage); `PerTenantUsage` as the model-agnostic per-tenant signal (counts + latency) with a worked example, and `FanOutObserver` to run it beside a Prometheus/InMemory observer; why dollar cost is the deployer's (model pricing is policy — multiply the usage by your rate); and the Non-goals (no storage partitioning, no token/$ cost, no quota). Add "### Multi-tenancy & per-tenant cost (opt-in)" to `README.md` and "### Đa tenant & chi phí theo tenant (tùy chọn)" to `README.vi.md` after the reproducibility section, each linking the doc.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/multi-tenancy.md README.md README.vi.md
git commit -m "feat: re-export multi-tenancy surface; docs"
```
