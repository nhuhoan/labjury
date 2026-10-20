"""Prometheus-backed :class:`~labjury.observability.Observer` reference exporter.

Requires the ``prometheus`` extra (``pip install labjury[prometheus]``). Maps the
four terminal-outcome hooks onto a labeled counter, and observes per-decision
latency into a histogram. LabJury starts **no** ``/metrics`` server — the
deployer owns serving (``prometheus_client.start_http_server``); this class only
maintains the collectors.

One exporter per registry per process: building two on the same registry raises
``prometheus_client``'s duplicate-timeseries error. Pass a dedicated
:class:`~prometheus_client.CollectorRegistry` to isolate.
"""

from __future__ import annotations

import prometheus_client

from labjury.results import ItemResult


class PrometheusObserver:
    def __init__(self, registry=None, namespace: str = "labjury") -> None:
        registry = registry if registry is not None else prometheus_client.REGISTRY
        # name the counter without the `_total` suffix; prometheus_client
        # appends it, yielding the sample `{namespace}_decisions_total`.
        self._decisions = prometheus_client.Counter(
            f"{namespace}_decisions",
            "LabJury terminal decision outcomes.",
            ["outcome"],
            registry=registry,
        )
        self._latency = prometheus_client.Histogram(
            f"{namespace}_decision_latency_seconds",
            "End-to-end per-decision latency.",
            registry=registry,
        )

    def on_decided(self, result: ItemResult) -> None:
        self._decisions.labels(outcome="decided").inc()
        self._observe_latency(result)

    def on_review(self, result: ItemResult) -> None:
        self._decisions.labels(outcome="review").inc()
        self._observe_latency(result)

    def on_failed(self, result: ItemResult) -> None:
        self._decisions.labels(outcome="failed").inc()

    def on_retry_later(self, result: ItemResult) -> None:
        self._decisions.labels(outcome="retry_later").inc()

    def _observe_latency(self, result: ItemResult) -> None:
        if result.latency_ms is not None:
            self._latency.observe(result.latency_ms / 1000.0)
