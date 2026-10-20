# Telemetry — Prometheus exporter reference backend — design

**Date:** 2026-10-20
**Tier / step:** Enterprise readiness — Tier 1, step 3 (telemetry).
**Depends on:** the existing `Observer` protocol and `InMemoryObserver`
(`src/labjury/observability.py`), and the `ItemResult` type
(`src/labjury/results.py`).

## Intent and the why

A decision system deployed at a large company must be observable in the stack
that company already runs. LabJury already has the right seam: the `Observer`
protocol, called once per terminal outcome. What it lacks is a reference
exporter that turns those calls into metrics an on-call engineer or a cost owner
can actually see on a dashboard. This step ships one — `PrometheusObserver` —
plus the one piece of signal the current hooks cannot carry but every on-call
engineer needs first at 3am: **per-decision latency**.

This mirrors steps 1 and 2b exactly: a reference backend in `labjury.contrib.*`,
behind its own extra, with the real contract staying the public protocol. A
company that runs OpenTelemetry, Datadog, or StatsD writes its own `Observer`
the same way; we ship one good, runnable example.

## Why Prometheus (CTO call, flagged for veto)

The roadmap named "OTel/Prometheus." One solid step ships **one** reference
exporter; **Prometheus**:

1. **Fully testable in-process, no infrastructure.** `prometheus_client` keeps
   counters in a `CollectorRegistry` you can read sample values from directly —
   no collector, no HTTP, no scrape loop needed to assert behavior. OTel's
   metrics path wants a meter provider + exporter + (usually) a collector, and
   its Python API has churned; that is heavier to ship *solidly* in one step.
2. **One tiny, stable, pure-Python dependency** (`prometheus_client`), behind
   `labjury[prometheus]`. The zero-dependency core is untouched.
3. **Pull-based scraping is the most common ops pattern**, and it keeps LabJury
   out of owning the serving: the exporter only maintains collectors; the
   deployer owns the `/metrics` endpoint and scrape config.
4. **OpenTelemetry is then the documented near-trivial variant** — the same
   `Observer` shape, a different client — exactly as Postgres is to SQLite.

## Why per-decision latency, and why it goes on `ItemResult`

Outcome counts (decided/review/failed/retry_later) already flow through the four
hooks; from them Prometheus derives throughput, review-rate, and failure-rate
via PromQL. The one thing missing is **latency**, the first signal on-call needs
and the one the engine alone knows. The engine measures it and attaches it to
the result it already hands every hook — a new **optional** field
`ItemResult.latency_ms: float | None = None`. This is non-breaking: the
`Observer` protocol signature is unchanged (still four hooks taking
`ItemResult`), existing observers ignore the new field, and `ItemResult(id,
status)` still constructs. Latency measurement is a *mechanism*, which the
engine owns; it adds no dependency.

## Goals

- `PrometheusObserver` in `labjury.contrib.prometheus_observer`, satisfying the
  `Observer` protocol (`isinstance(obs, Observer)` is `True`).
- Exports a **counter** `labjury_decisions_total{outcome=...}` incremented once
  per hook, and a **histogram** `labjury_decision_latency_seconds` observed when
  a decided/review result carries a latency.
- The engine measures end-to-end per-item latency in `process()` and sets
  `ItemResult.latency_ms` before the observer hook runs.
- Fully in-process tests reading sample values from a fresh `CollectorRegistry`.
- `labjury[prometheus]` extra; zero-dependency core unchanged; core never
  imports contrib.

## Non-goals

- No OpenTelemetry / Datadog / StatsD exporter this step (documented variant).
- **No HTTP `/metrics` server** started by LabJury — the deployer calls
  `prometheus_client.start_http_server(...)` (or mounts the ASGI app) themselves.
  We own the collectors, not the serving.
- No tracing/spans, no per-stage latency breakdown (proposer vs scorer vs
  policy) — one end-to-end latency per decision is the step-3 signal; a span
  tree is a later step if wanted.
- No new plugin kind / entry-point group for observers — the observer is a
  constructor argument to `Engine`, not discovered (it already works this way).

## Anti-goals (failure even if it works)

- Making the core import `prometheus_client` or `labjury.contrib`.
- Breaking the public `Observer` protocol or the `ItemResult` constructor.
- Presenting Prometheus as *the* telemetry rather than *an example*.
- A latency measurement that changes a decision's outcome or can break
  `process()` if the clock misbehaves.

## The how — decided

**Core enrichment (not contrib):**
- `src/labjury/results.py`: add `latency_ms: float | None = None` to
  `ItemResult` (last field, defaulted — backward-compatible).
- `src/labjury/engine.py`: in `process()`, wrap the `_run` call with
  `time.perf_counter()`; on the normal and the `except` paths set
  `result.latency_ms = (end - start) * 1000.0` before calling `self._finish`.
  `process_batch`'s pre-admission `RETRY_LATER` results keep `latency_ms=None`
  (no decision ran).

**The exporter (`labjury.contrib.prometheus_observer.PrometheusObserver`):**
- Constructor: `PrometheusObserver(registry=None, namespace="labjury")`.
  `registry` defaults to `prometheus_client.REGISTRY` (the global one, so
  scraping "just works"); tests pass a fresh `CollectorRegistry()`. `namespace`
  prefixes metric names.
- Builds two collectors on that registry:
  - `Counter(f"{namespace}_decisions_total", "...", ["outcome"], registry=registry)`
  - `Histogram(f"{namespace}_decision_latency_seconds", "...", registry=registry)`
- `on_decided`/`on_review`/`on_failed`/`on_retry_later`: each increments
  `counter.labels(outcome=<name>).inc()`. `on_decided` and `on_review`
  additionally, when `result.latency_ms is not None`, call
  `histogram.observe(result.latency_ms / 1000.0)` (Prometheus latency is in
  seconds). Hooks are synchronous, matching the protocol and the client.
- Used by direct import (like `RedisTaxonomyStore`, `SqliteAuditLog`); not
  entry-pointed, not re-exported from top-level `labjury`.

**No dedicated conformance suite** (deliberate deviation from steps 1/2b): the
`Observer` protocol is four sync methods and is `@runtime_checkable`, so
`isinstance(obs, Observer)` already is the structural contract check. The
exporter's own tests prove the counter/histogram behavior. Adding an
`assert_observer_contract` would restate the `isinstance` check for little gain;
if parity is wanted later it is a small add.

## What's left to the builder

- Exact metric help strings and the `time.perf_counter()` wrapping.
- Tests (`tests/test_prometheus_observer.py`, in-process, fresh
  `CollectorRegistry` each): (1) the exporter satisfies `isinstance(_, Observer)`;
  (2) each hook increments `labjury_decisions_total` for its outcome
  (read back via `registry.get_sample_value`); (3) a decided result carrying
  `latency_ms` records a histogram observation (`..._count` sample == 1);
  (4) `namespace` prefixes the metric names.
- An engine test (`tests/test_engine.py`): a processed item's `ItemResult` has a
  non-None `latency_ms`; a pre-admission `RETRY_LATER` from `process_batch` has
  `latency_ms is None`.
- `labjury[prometheus]` extra in `pyproject.toml` (`prometheus_client`).
- Docs: new `docs/observability.md` (bring-your-own-exporter + the Prometheus
  reference, noting OTel as the same-shape variant and that the deployer owns the
  `/metrics` server); one-line pointers in `README.md` and `README.vi.md`.

## Builder check

Self builder-check (honoring the standing no-spawn-without-asking constraint;
weaker than an independent reviewer, noted as such). Open question a builder
would raise and its settled answer: *"If two `PrometheusObserver`s are built on
the same default global registry, won't the second raise `Duplicated
timeseries`?"* — Yes; `prometheus_client` forbids registering two collectors of
the same name on one registry. This is inherent to Prometheus and correct
behavior (one exporter per registry per process). Documented in
`docs/observability.md`: build one `PrometheusObserver` per process, or pass a
dedicated `CollectorRegistry`. Settled; recorded here.
