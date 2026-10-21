import pytest

from labjury import ItemResult, Status
from labjury.observability import (
    FanOutObserver,
    InMemoryObserver,
    Observer,
    PerTenantUsage,
)


def _r(tenant, status, latency=None):
    return ItemResult("c", status, latency_ms=latency, tenant=tenant)


class _RecordingObserver:
    def __init__(self):
        self.calls = []

    def on_decided(self, result):
        self.calls.append(("on_decided", result))

    def on_review(self, result):
        self.calls.append(("on_review", result))

    def on_failed(self, result):
        self.calls.append(("on_failed", result))

    def on_retry_later(self, result):
        self.calls.append(("on_retry_later", result))


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
    assert m.snapshot() == {}


def test_snapshot_is_isolated():
    m = PerTenantUsage()
    m.on_failed(_r("acme", Status.FAILED, 5.0))
    snap = m.snapshot()
    snap.clear()
    assert m.for_tenant("acme").failed == 1


def test_usage_values_are_copies():
    m = PerTenantUsage()
    m.on_decided(_r("acme", Status.DECIDED, 10.0))
    m.for_tenant("acme").decided = 99
    m.snapshot()["acme"].total_latency_ms = 999.0
    assert m.for_tenant("acme").decided == 1
    assert m.for_tenant("acme").total_latency_ms == 10.0


def test_fanout_forwards_all_hooks():
    a, b = _RecordingObserver(), _RecordingObserver()
    fan = FanOutObserver([a, b])
    r = _r("acme", Status.DECIDED, 1.0)
    fan.on_decided(r)
    fan.on_review(r)
    fan.on_failed(r)
    fan.on_retry_later(r)
    for obs in (a, b):
        assert [h for h, _ in obs.calls] == [
            "on_decided",
            "on_review",
            "on_failed",
            "on_retry_later",
        ]


def test_meters_are_observers():
    assert isinstance(PerTenantUsage(), Observer)
    assert isinstance(FanOutObserver([]), Observer)


def test_counters_and_review_rate():
    obs = InMemoryObserver()
    obs.on_decided(ItemResult("a", Status.DECIDED))
    obs.on_review(ItemResult("b", Status.REVIEW))
    obs.on_review(ItemResult("c", Status.REVIEW))
    assert obs.decided == 1 and obs.review == 2
    assert obs.review_rate() == pytest.approx(2 / 3)


def test_review_rate_zero_when_empty():
    assert InMemoryObserver().review_rate() == 0.0


def test_failed_and_retry_counters():
    obs = InMemoryObserver()
    obs.on_failed(ItemResult("a", Status.FAILED, error="boom"))
    obs.on_retry_later(ItemResult("b", Status.RETRY_LATER))
    assert obs.failed == 1 and obs.retry_later == 1
