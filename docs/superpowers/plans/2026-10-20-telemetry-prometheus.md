# Prometheus Telemetry Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `PrometheusObserver` reference exporter under `labjury.contrib`
plus a non-breaking per-decision latency signal on `ItemResult`, so outcomes,
throughput, and latency are visible on a Prometheus dashboard.

**Architecture:** The engine measures end-to-end latency per item and attaches
it to the `ItemResult` it already hands every `Observer` hook (new optional
field, protocol unchanged). A contrib `PrometheusObserver` maps the four
outcome hooks to a labeled counter and observes latency into a histogram on a
`prometheus_client` `CollectorRegistry`.

**Tech Stack:** `prometheus_client` (behind the `labjury[prometheus]` extra),
stdlib `time.perf_counter`.

**Spec:** `docs/superpowers/specs/2026-10-20-telemetry-prometheus-design.md`

## Global Constraints

- Zero-dependency core unchanged; `prometheus_client` only under the
  `labjury[prometheus]` extra; the core never imports `labjury.contrib`.
- The public `Observer` protocol signature stays unchanged (four sync hooks
  taking `ItemResult`); `ItemResult(id, status)` must still construct.
- `PrometheusObserver` is used by direct import — not entry-point registered,
  not re-exported from top-level `labjury`.
- LabJury starts no HTTP `/metrics` server; the deployer owns serving.
- Metric names: `labjury_decisions_total{outcome=...}` (counter),
  `labjury_decision_latency_seconds` (histogram); `namespace` (default
  `"labjury"`) is the name prefix. Latency is observed in **seconds**.

## Review Focus

- **Two observers on one registry**: building a second `PrometheusObserver` on
  the same (default global) registry raises `prometheus_client`'s duplicate-
  timeseries error — inherent and correct; documented, not coded around. Pinned
  by a test asserting a fresh `CollectorRegistry` gives an independent observer
  (Task 2).
- **`retry_later` carries no latency**: a pre-admission `RETRY_LATER` from
  `process_batch` never ran a decision, so `latency_ms is None` and no histogram
  observation happens — pinned in Task 1 (engine) and Task 2 (the latency hook
  only observes on decided/review).
- **Failed item still times and counts**: an item that raises inside `_run`
  still gets a `latency_ms` and an `on_failed` increment — pinned in Task 1.
- **`namespace` actually prefixes names**: a custom namespace changes the
  exported metric name — pinned in Task 2.
- Core-import isolation (core pulls in neither contrib nor `prometheus_client`)
  is already pinned by the subprocess test in `tests/test_redis_taxonomy.py`.

---

### Task 1: Per-decision latency on `ItemResult`

**Files:**
- Modify: `src/labjury/results.py` (add field to `ItemResult`)
- Modify: `src/labjury/engine.py` (`process`, measure latency)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: existing `Engine.process` / `process_batch`, `ItemResult`.
- Produces: `ItemResult.latency_ms: float | None` — set to elapsed
  milliseconds by `Engine.process` for every item it runs (decided, review,
  failed), left `None` for pre-admission `RETRY_LATER` results.

- [ ] **Step 1: Write the failing tests**

```python
async def test_processed_item_records_latency():
    eng = make_engine()
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.latency_ms is not None and r.latency_ms >= 0.0

async def test_failed_item_still_records_latency():
    eng = make_engine(fail_on_id="i1")
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.status is Status.FAILED and r.latency_ms is not None

async def test_pre_admission_retry_later_has_no_latency():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    results = await eng.process_batch([Item(f"i{n}", {"text": "t"}) for n in range(4)])
    retry = [r for r in results if r.status is Status.RETRY_LATER]
    assert retry and all(r.latency_ms is None for r in retry)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engine.py -k latency -v`
Expected: FAIL — `ItemResult` has no attribute `latency_ms` (or the attribute
is always `None`).

- [ ] **Step 3: Add the field and measure it**

- In `src/labjury/results.py`, add `latency_ms: float | None = None` as the last
  field of `ItemResult`.
- In `src/labjury/engine.py` `process`, record `start = time.perf_counter()`
  before the `try`, and after `result` is obtained (both the normal and the
  `except` path) set `result.latency_ms = (time.perf_counter() - start) * 1000.0`
  before `await self._finish(result)`. Add `import time`. Do not touch the
  pre-admission `RETRY_LATER` construction in `process_batch`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_engine.py -k latency -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass (prior 76 + 3), 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/results.py src/labjury/engine.py tests/test_engine.py
git commit -m "feat: per-decision latency_ms on ItemResult"
```

---

### Task 2: `PrometheusObserver` exporter

**Files:**
- Create: `src/labjury/contrib/prometheus_observer.py`
- Modify: `pyproject.toml` (add `prometheus` extra)
- Test: `tests/test_prometheus_observer.py`

**Interfaces:**
- Consumes: `ItemResult` with `latency_ms` (Task 1); `labjury.observability.Observer`;
  `prometheus_client.{Counter, Histogram, CollectorRegistry, REGISTRY}`.
- Produces: `PrometheusObserver(registry=None, namespace="labjury")` with the
  four `Observer` hooks (`on_decided`, `on_review`, `on_failed`,
  `on_retry_later`), each sync.

- [ ] **Step 1: Add the `prometheus` extra**

In `pyproject.toml` `[project.optional-dependencies]`, add
`prometheus = ["prometheus_client>=0.19"]`.

- [ ] **Step 2: Write the failing tests**

```python
from prometheus_client import CollectorRegistry
from labjury.observability import Observer
from labjury.results import ItemResult, Status, Verdict, Action
from labjury.contrib.prometheus_observer import PrometheusObserver

def _decided(latency_ms=12.0):
    v = Verdict(Action.ACCEPT, ["food"], {}, [], "ok")
    return ItemResult("i1", Status.DECIDED, verdict=v, latency_ms=latency_ms)

def test_is_an_observer():
    assert isinstance(PrometheusObserver(registry=CollectorRegistry()), Observer)

def test_each_outcome_increments_its_counter():
    reg = CollectorRegistry()
    obs = PrometheusObserver(registry=reg)
    obs.on_decided(_decided())
    obs.on_review(ItemResult("i2", Status.REVIEW, latency_ms=5.0))
    obs.on_failed(ItemResult("i3", Status.FAILED))
    obs.on_retry_later(ItemResult("i4", Status.RETRY_LATER))
    g = reg.get_sample_value
    assert g("labjury_decisions_total", {"outcome": "decided"}) == 1.0
    assert g("labjury_decisions_total", {"outcome": "review"}) == 1.0
    assert g("labjury_decisions_total", {"outcome": "failed"}) == 1.0
    assert g("labjury_decisions_total", {"outcome": "retry_later"}) == 1.0

def test_latency_observed_only_when_present():
    reg = CollectorRegistry()
    obs = PrometheusObserver(registry=reg)
    obs.on_decided(_decided(latency_ms=20.0))
    obs.on_retry_later(ItemResult("i4", Status.RETRY_LATER))  # no latency
    assert reg.get_sample_value("labjury_decision_latency_seconds_count") == 1.0

def test_namespace_prefixes_metric_names():
    reg = CollectorRegistry()
    PrometheusObserver(registry=reg, namespace="lj_test").on_failed(
        ItemResult("i", Status.FAILED))
    assert reg.get_sample_value(
        "lj_test_decisions_total", {"outcome": "failed"}) == 1.0

def test_fresh_registry_gives_independent_observer():
    # two observers on two registries coexist (duplicate-timeseries only bites
    # on a shared registry — that is prometheus_client's contract, not ours).
    PrometheusObserver(registry=CollectorRegistry())
    PrometheusObserver(registry=CollectorRegistry())  # must not raise
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_prometheus_observer.py -v`
Expected: FAIL — `No module named 'labjury.contrib.prometheus_observer'`.

- [ ] **Step 4: Implement `PrometheusObserver`**

In `src/labjury/contrib/prometheus_observer.py`:
- `__init__(self, registry=None, namespace="labjury")`: `registry = registry or
  prometheus_client.REGISTRY`; build
  `self._decisions = Counter(f"{namespace}_decisions", <help>, ["outcome"],
  registry=registry)` — name it **without** the `_total` suffix;
  `prometheus_client` appends `_total` to counter samples, so the exported
  sample is `{namespace}_decisions_total`. Build `self._latency = Histogram(
  f"{namespace}_decision_latency_seconds", <help>, registry=registry)` (the
  histogram name is used verbatim; the client adds `_count`/`_sum`/`_bucket`).
- Each hook increments `self._decisions.labels(outcome=<name>).inc()` with the
  matching outcome name (`"decided"`, `"review"`, `"failed"`, `"retry_later"`).
- `on_decided` and `on_review` additionally: `if result.latency_ms is not None:
  self._latency.observe(result.latency_ms / 1000.0)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_prometheus_observer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: all pass; 1 skipped.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/contrib/prometheus_observer.py tests/test_prometheus_observer.py pyproject.toml
git commit -m "feat: PrometheusObserver telemetry reference exporter"
```

---

### Task 3: Documentation

**Files:**
- Create: `docs/observability.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `PrometheusObserver(registry=None, namespace="labjury")` (Task 2),
  `ItemResult.latency_ms` (Task 1).
- Produces: nothing code depends on.

- [ ] **Step 1: Write `docs/observability.md`**

Cover: the `Observer` protocol as the contract (bring your own exporter), the
Prometheus reference backend (`pip install labjury[prometheus]`, construct with
an optional `registry`/`namespace`, pass to `Engine(observer=...)`), the two
metrics and that review-rate/throughput come from PromQL over the counter, that
the deployer owns the `/metrics` server (`prometheus_client.start_http_server`),
the one-observer-per-registry rule, and that OpenTelemetry is the same `Observer`
shape with a different client.

- [ ] **Step 2: Add one-line pointers to `README.md` and `README.vi.md`**

In each, a sentence that a Prometheus reference exporter ships
(`labjury.contrib.prometheus_observer.PrometheusObserver`, `labjury[prometheus]`)
linking `docs/observability.md`.

- [ ] **Step 3: Verify the documented import and constructor**

Run: `python -c "from labjury.contrib.prometheus_observer import PrometheusObserver; from prometheus_client import CollectorRegistry; PrometheusObserver(registry=CollectorRegistry())"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add docs/observability.md README.md README.vi.md
git commit -m "docs: Prometheus telemetry exporter"
```
