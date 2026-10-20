# Multi-tenancy — tenant attribution & per-tenant usage accounting

**Status:** design (CTO-decided; owner delegated design authority, "ok" 2026-10-20) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness **Tier 2** (operability at scale), **item 3 of 5** — multi-tenancy + per-tenant cost. Builds on the Tier-1 audit trail and observability.

## Intent and the why

One LabJury deployment serves many tenants (companies, teams, brands). Two
enterprise needs follow:

1. **Attribution** — every decision, result, and audit record must be traceable to
   the tenant it was made for, so a deployer can partition their audit store, filter
   dashboards, and bill by tenant.
2. **Per-tenant cost** — "which tenant is consuming the budget" must be answerable.

As everywhere in LabJury, the framework owns the **mechanism**, not the policy:

- It does **not** own storage partitioning — the deployer keys their own
  `TaxonomyStore` / `RubricStore` / `AuditLog` / `Cache` by tenant ("bring your own
  storage"). LabJury carries the tenant identity *through* a decision so those stores
  and dashboards can use it.
- It does **not** own money. A dollar cost depends on which model and which
  contract pricing — that is deployer policy. LabJury provides the model-agnostic
  usage signal it can measure itself (decision counts and latency per tenant);
  multiplying by a rate is the deployer's.

So this slice ships two mechanisms: **tenant attribution** threaded through the
decision, and a reference **per-tenant usage meter** built on the existing
observability seam.

## Goals

- **Tenant attribution (additive, non-breaking):**
  - `Item.tenant: str | None = None` — the unit of work carries who it is for.
  - `ItemResult.tenant: str | None = None` — the engine copies `item.tenant` onto
    every result it produces (main path, top-level `FAILED`, batch pre-admission
    `RETRY_LATER`, and batch gather-exception `FAILED`).
  - `AuditEvent.tenant: str | None = None` — the engine records `item.tenant` on both
    the full decision event and the cache-hit event; `to_dict`/`from_dict` carry it
    (older records without the key decode to `None`).
- **Per-tenant usage meter (reference, zero-dep, in core):**
  - `TenantUsage` — a dataclass tally: `decided`, `review`, `failed`, `retry_later`
    (ints), `total_latency_ms` (float), `latency_count` (int); property
    `avg_latency_ms -> float | None` (`total/count`, or `None` when no samples).
  - `PerTenantUsage` — an `Observer` implementation that buckets by
    `result.tenant`: each hook increments the matching counter and, when
    `result.latency_ms is not None`, accumulates latency. Readers: `for_tenant(tenant)
    -> TenantUsage` (a zero tally for an unseen tenant, never `KeyError`) and
    `snapshot() -> dict[str | None, TenantUsage]`.
- **Observer fan-out (so the meter is usable alongside existing observers):**
  - `FanOutObserver(observers)` — an `Observer` that forwards each of the four hooks
    to every child observer, in order. Lets a deployer run `PerTenantUsage` beside a
    `PrometheusObserver` / `InMemoryObserver` even though the engine takes a single
    observer.
- **Public surface:** re-export `TenantUsage`, `PerTenantUsage`, `FanOutObserver`
  from `labjury`; add to `test_public_api.py`.
- **Docs:** `docs/multi-tenancy.md` + bilingual README pointers.

## Non-goals / anti-goals

- **No token-level or dollar cost.** The engine measures decision counts and latency,
  which it owns end-to-end. Token/$ cost originates in the scorer and depends on model
  pricing; reporting it would require changing the `Scorer` contract and encoding
  pricing policy. Documented as the extension (a scorer reporting usage through a side
  channel), not built.
- **No storage partitioning.** LabJury does not shard or namespace any store by tenant;
  it carries the tenant so the deployer's stores can. Same "bring your own storage"
  rule as every other tier.
- **No rate limiting, quota, or admission control per tenant.** Those are a different
  mechanism (backpressure/scheduling); this slice is attribution + measurement only.
- **No change to the `Observer` protocol** (still four sync hooks) or any plugin
  contract. `PerTenantUsage` and `FanOutObserver` are implementations; the tenant
  fields are additive defaults.
- **No engine behavior change beyond threading an already-present value** — the engine
  copies `item.tenant` onto outputs; it does not branch on it.

## Constraints (inherited)

- Core `dependencies = []`; stdlib only; mechanisms live in core (`labjury.state` /
  `labjury.results` / `labjury.audit` for the fields, `labjury.observability` for the
  meters). Core never imports `labjury.contrib`.
- No public plugin contract change; all additions are optional defaulted fields or new
  classes. Existing positional constructions of `Item`/`ItemResult`/`AuditEvent` keep
  working (the new fields are appended with defaults).
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### Tenant fields + engine threading

`Item` and `ItemResult` gain `tenant: str | None = None` (appended, defaulted).
`AuditEvent` gains `tenant: str | None = None` (appended before the
`default_factory` fields, carried in `to_dict`/`from_dict`). In `engine.py`:

- `process`: after computing `result`, set `result.tenant = item.tenant` (same place
  it sets `latency_ms`).
- `process_batch`: set `.tenant` on the pre-admission `RETRY_LATER` result and on the
  gather-exception `FAILED` result.
- `_run`: pass `tenant=item.tenant` to both `AuditEvent(...)` constructions.

The engine never reads `tenant` to make a decision — it only attributes outputs.

### `PerTenantUsage` + `TenantUsage` + `FanOutObserver` (`observability.py`)

```python
@dataclass
class TenantUsage:
    decided: int = 0
    review: int = 0
    failed: int = 0
    retry_later: int = 0
    total_latency_ms: float = 0.0
    latency_count: int = 0
    @property
    def avg_latency_ms(self) -> float | None:
        return self.total_latency_ms / self.latency_count if self.latency_count else None

class PerTenantUsage:   # Observer
    def for_tenant(self, tenant: str | None) -> TenantUsage: ...
    def snapshot(self) -> dict[str | None, TenantUsage]: ...

class FanOutObserver:   # Observer
    def __init__(self, observers): ...
```

`PerTenantUsage` keeps `dict[str | None, TenantUsage]`; each hook does
`u = self._by_tenant.setdefault(result.tenant, TenantUsage())`, increments the right
counter, and if `result.latency_ms is not None` adds it to `total_latency_ms` and
increments `latency_count`. `for_tenant` returns a fresh zero `TenantUsage` for an
unseen tenant (never inserts, never raises). The `None` tenant bucket holds untagged
traffic.

### Public surface

Re-exported from `labjury` under an observability group: `TenantUsage`,
`PerTenantUsage`, `FanOutObserver`. Added to `test_public_api.py`.

## What's left to the builder

- Internal representation of `PerTenantUsage` (a dict is the obvious choice; tests pin
  behavior, not representation).
- Whether `snapshot` returns the live dict or a copy — return a shallow copy so a caller
  can't mutate internals (the builder decides the copy depth; tests check isolation of
  the mapping).

## Review focus (inputs the tests must pin)

- **Tenant flows end-to-end** — an `Item(tenant="acme")` processed by the engine yields
  an `ItemResult.tenant == "acme"` and an `AuditEvent.tenant == "acme"` — pinned in
  Task 1.
- **`AuditEvent.tenant` round-trips** through `to_dict`/`from_dict`, and a dict without
  the key decodes to `None` (backward-compatible) — pinned in Task 1.
- **A result with no tenant lands in the `None` bucket**, kept separate from a tagged
  tenant — pinned in Task 2.
- **`avg_latency_ms` is `None` with no samples** and the mean otherwise; a
  `retry_later` result (latency `None`) increments the count but contributes no latency
  — pinned in Task 2.
- **`FanOutObserver` forwards every hook to every child** in order — pinned in Task 2.
- **`for_tenant` on an unseen tenant returns a zero tally**, not `KeyError` — pinned in
  Task 2.
