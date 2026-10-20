"""Default, in-memory plugin implementations.

Deliberately dependency-free: a Redis cache or a durable sink are reference
plugins (Plan 2), not core. These let the engine run end-to-end in tests and
single-process deployments.
"""

from __future__ import annotations

from labjury.audit import AuditEvent
from labjury.results import ItemResult, Verdict


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, Verdict] = {}

    async def get(self, key: str) -> Verdict | None:
        return self._store.get(key)

    async def put(self, key: str, verdict: Verdict) -> None:
        self._store[key] = verdict


class CollectingSink:
    def __init__(self) -> None:
        self.results: list[ItemResult] = []

    async def emit(self, result: ItemResult) -> None:
        self.results.append(result)


class NullAuditLog:
    """The opt-out: satisfies the AuditLog protocol but retains nothing.

    The safe zero-cost default so core stays lean and auditing is explicit.
    """

    async def record(self, event: AuditEvent) -> None:
        return None

    async def by_correlation(self, correlation_id: str) -> list[AuditEvent]:
        return []


class InMemoryAuditLog:
    """Append-only in-memory audit log for dev, tests, and single-process use."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self._events.append(event)

    async def by_correlation(self, correlation_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.correlation_id == correlation_id]
