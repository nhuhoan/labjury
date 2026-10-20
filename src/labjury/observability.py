"""Observability hooks.

Quality and cost are only manageable if measured: the engine calls one hook
per terminal outcome. ``InMemoryObserver`` is the dependency-free default;
exporters (Prometheus, OTEL) are reference plugins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from labjury.results import ItemResult


@runtime_checkable
class Observer(Protocol):
    def on_decided(self, result: ItemResult) -> None: ...

    def on_review(self, result: ItemResult) -> None: ...

    def on_failed(self, result: ItemResult) -> None: ...

    def on_retry_later(self, result: ItemResult) -> None: ...


class InMemoryObserver:
    def __init__(self) -> None:
        self.decided = 0
        self.review = 0
        self.failed = 0
        self.retry_later = 0

    def on_decided(self, result: ItemResult) -> None:
        self.decided += 1

    def on_review(self, result: ItemResult) -> None:
        self.review += 1

    def on_failed(self, result: ItemResult) -> None:
        self.failed += 1

    def on_retry_later(self, result: ItemResult) -> None:
        self.retry_later += 1

    def review_rate(self) -> float:
        total = self.decided + self.review + self.failed + self.retry_later
        return self.review / total if total else 0.0


@dataclass
class TenantUsage:
    """One tenant's accumulated usage: outcome counts and decision latency.

    This is the model-agnostic cost signal the engine can measure itself. A
    dollar figure is the deployer's: multiply by the per-model rate they pay."""

    decided: int = 0
    review: int = 0
    failed: int = 0
    retry_later: int = 0
    total_latency_ms: float = 0.0
    latency_count: int = 0

    @property
    def avg_latency_ms(self) -> float | None:
        return self.total_latency_ms / self.latency_count if self.latency_count else None


class PerTenantUsage:
    """An :class:`Observer` that tallies usage per ``result.tenant``.

    Untagged traffic (``tenant is None``) lands in its own bucket. Latency is
    accumulated only when the result carries one (a pre-admission
    ``RETRY_LATER`` has none)."""

    def __init__(self) -> None:
        self._by_tenant: dict[str | None, TenantUsage] = {}

    def _bump(self, result: ItemResult, counter: str) -> None:
        usage = self._by_tenant.setdefault(result.tenant, TenantUsage())
        setattr(usage, counter, getattr(usage, counter) + 1)
        if result.latency_ms is not None:
            usage.total_latency_ms += result.latency_ms
            usage.latency_count += 1

    def on_decided(self, result: ItemResult) -> None:
        self._bump(result, "decided")

    def on_review(self, result: ItemResult) -> None:
        self._bump(result, "review")

    def on_failed(self, result: ItemResult) -> None:
        self._bump(result, "failed")

    def on_retry_later(self, result: ItemResult) -> None:
        self._bump(result, "retry_later")

    def for_tenant(self, tenant: str | None) -> TenantUsage:
        """This tenant's usage, or a fresh zero tally — never inserts or raises."""
        return self._by_tenant.get(tenant) or TenantUsage()

    def snapshot(self) -> dict[str | None, TenantUsage]:
        """A shallow copy of the per-tenant mapping (the caller can't mutate ours)."""
        return dict(self._by_tenant)


class FanOutObserver:
    """An :class:`Observer` that forwards each hook to several child observers.

    The engine takes a single observer; this composes many (e.g. a
    :class:`PerTenantUsage` beside a Prometheus exporter)."""

    def __init__(self, observers: Iterable[Observer]) -> None:
        self._observers = list(observers)

    def on_decided(self, result: ItemResult) -> None:
        for obs in self._observers:
            obs.on_decided(result)

    def on_review(self, result: ItemResult) -> None:
        for obs in self._observers:
            obs.on_review(result)

    def on_failed(self, result: ItemResult) -> None:
        for obs in self._observers:
            obs.on_failed(result)

    def on_retry_later(self, result: ItemResult) -> None:
        for obs in self._observers:
            obs.on_retry_later(result)
