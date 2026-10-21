"""Redis-backed :class:`~labjury.plugins.Cache` reference backend.

Requires the ``redis`` extra (``pip install labjury[redis]``). The async client
is injected, never created here, so the deployer owns pooling, TLS and failover
— mirroring :class:`~labjury.contrib.redis_taxonomy.RedisTaxonomyStore`.

A :class:`~labjury.results.Verdict` is round-tripped through JSON via the audit
module's ``verdict_to_dict`` / ``verdict_from_dict`` seam. ``ttl_s`` sets an
optional per-key expiry (``None`` = no expiry, matching ``InMemoryCache``);
moderation verdicts are often safe to expire as content or policy changes.

Used by direct import — not re-exported at the top level and not entry-pointed,
since it needs a client argument.
"""

from __future__ import annotations

import json
from typing import Any

from labjury.audit import verdict_from_dict, verdict_to_dict
from labjury.results import Verdict


class RedisCache:
    def __init__(
        self,
        client: Any,
        namespace: str = "labjury:cache",
        ttl_s: int | None = None,
    ) -> None:
        self._r = client
        self._namespace = namespace
        self._ttl = ttl_s

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def get(self, key: str) -> Verdict | None:
        raw = await self._r.get(self._key(key))
        if raw is None:
            return None
        return verdict_from_dict(json.loads(raw))

    async def put(self, key: str, verdict: Verdict) -> None:
        await self._r.set(
            self._key(key),
            json.dumps(verdict_to_dict(verdict)),
            ex=self._ttl,
        )
