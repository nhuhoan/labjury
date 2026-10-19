"""Default, in-memory plugin implementations.

Deliberately dependency-free: a Redis cache or a durable sink are reference
plugins (Plan 2), not core. These let the engine run end-to-end in tests and
single-process deployments.
"""

from __future__ import annotations

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
