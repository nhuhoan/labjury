"""Observability hooks.

Quality and cost are only manageable if measured: the engine calls one hook
per terminal outcome. ``InMemoryObserver`` is the dependency-free default;
exporters (Prometheus, OTEL) are reference plugins.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
