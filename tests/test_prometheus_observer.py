from prometheus_client import CollectorRegistry

from labjury.contrib.prometheus_observer import PrometheusObserver
from labjury.observability import Observer
from labjury.results import Action, ItemResult, Status, Verdict


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
        ItemResult("i", Status.FAILED)
    )
    assert (
        reg.get_sample_value("lj_test_decisions_total", {"outcome": "failed"}) == 1.0
    )


def test_fresh_registry_gives_independent_observer():
    # two observers on two registries coexist (duplicate-timeseries only bites
    # on a shared registry — that is prometheus_client's contract, not ours).
    PrometheusObserver(registry=CollectorRegistry())
    PrometheusObserver(registry=CollectorRegistry())  # must not raise
