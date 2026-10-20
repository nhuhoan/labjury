# Observability — metrics, and bringing your own exporter

Quality and cost are only manageable if measured. LabJury calls one `Observer`
hook per terminal outcome, and each hook receives the `ItemResult` — including
its `latency_ms` (end-to-end per-decision latency, measured by the engine).
Where those signals go is up to you. `PrometheusObserver` is **one reference
exporter, not a requirement** — the same way `Jev` is just one `Scorer`.

## The contract

An observer is any object with these four **synchronous** methods (the
`labjury.observability.Observer` protocol):

```python
def on_decided(self, result: ItemResult) -> None: ...
def on_review(self, result: ItemResult) -> None: ...
def on_failed(self, result: ItemResult) -> None: ...
def on_retry_later(self, result: ItemResult) -> None: ...
```

`result.latency_ms` is the decision's end-to-end latency in milliseconds, or
`None` for a pre-admission `RETRY_LATER` (no decision ran). Export to Datadog,
StatsD, OpenTelemetry, or your own store by writing a small class — no
inheritance, no base class, no change to LabJury core.

## The Prometheus reference exporter

```bash
pip install labjury[prometheus]
```

```python
import labjury as lj
from labjury.contrib.prometheus_observer import PrometheusObserver

engine = lj.Engine(..., observer=PrometheusObserver(namespace="labjury"))
```

It maintains two collectors:

- `labjury_decisions_total{outcome="decided|review|failed|retry_later"}` — a
  counter, one increment per decision. **Throughput, review-rate, and
  failure-rate all come from PromQL over this counter** (e.g.
  `rate(labjury_decisions_total{outcome="review"}[5m])`), so there is no
  separate gauge to keep consistent.
- `labjury_decision_latency_seconds` — a histogram of per-decision latency
  (observed for `decided` and `review` outcomes, which carry a latency).

`namespace` (default `"labjury"`) prefixes the metric names.

### You own the `/metrics` server

LabJury starts no HTTP server — serving metrics is your infrastructure, not the
framework's. Expose them the usual way:

```python
from prometheus_client import start_http_server
start_http_server(9090)  # Prometheus scrapes http://host:9090/metrics
```

### One exporter per registry

`PrometheusObserver` registers its collectors on a `CollectorRegistry` (the
global `prometheus_client.REGISTRY` by default). Building two on the **same**
registry raises `prometheus_client`'s duplicate-timeseries error — that is the
client's contract, not ours. Build one exporter per process, or pass a dedicated
registry to isolate:

```python
from prometheus_client import CollectorRegistry
PrometheusObserver(registry=CollectorRegistry())
```

## OpenTelemetry and others — the same shape

Prometheus is one option. An OpenTelemetry exporter is the **same `Observer`
shape** with a different client: increment an OTel counter in each hook and
record a histogram from `result.latency_ms`. Pass whichever you build straight
to `Engine(observer=...)`.
