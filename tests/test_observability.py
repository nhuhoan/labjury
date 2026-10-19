import pytest

from labjury import ItemResult, Status
from labjury.observability import InMemoryObserver


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
