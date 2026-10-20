"""Redis-backed :class:`~labjury.plugins.TaxonomyStore` reference backend.

Requires the ``redis`` extra (``pip install labjury[redis]``). The async
client is injected, never created here, so the deployer owns pooling, TLS and
failover — mirroring the dependency-injection style of ``LLMJudgeScorer``.

Two Redis sets hold the two open-world tiers; ``promote`` is a single atomic
``SMOVE``. ``meta`` is accepted for protocol compatibility but not persisted
in this step (nothing reads it yet).
"""

from __future__ import annotations

from typing import Any


class RedisTaxonomyStore:
    def __init__(self, client: Any, namespace: str = "labjury:tax") -> None:
        self._r = client
        self._official = f"{namespace}:official"
        self._proposed = f"{namespace}:proposed"

    async def is_known(self, label: str) -> bool:
        return bool(await self._r.sismember(self._official, label))

    async def propose(self, label: str, meta: dict | None = None) -> None:
        if not await self._r.sismember(self._official, label):
            await self._r.sadd(self._proposed, label)

    async def promote(self, label: str) -> None:
        await self._r.smove(self._proposed, self._official, label)
        await self._r.sadd(self._official, label)

    async def known_labels(self) -> set[str]:
        return set(await self._r.smembers(self._official))

    async def proposed_labels(self) -> set[str]:
        return set(await self._r.smembers(self._proposed))
