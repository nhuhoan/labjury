import os

import pytest

from labjury.contrib.redis_taxonomy import RedisTaxonomyStore
from labjury.testing import assert_taxonomy_store_contract


class FakeRedis:
    """Minimal in-memory async stand-in for the four Redis set commands used."""

    def __init__(self):
        self._sets: dict[str, set[str]] = {}

    async def sismember(self, key, member):
        return member in self._sets.get(key, set())

    async def sadd(self, key, *members):
        self._sets.setdefault(key, set()).update(members)

    async def smembers(self, key):
        return set(self._sets.get(key, set()))

    async def smove(self, src, dst, member):
        s = self._sets.get(src, set())
        if member not in s:
            return False
        s.discard(member)
        self._sets.setdefault(dst, set()).add(member)
        return True


async def test_redis_store_satisfies_contract():
    await assert_taxonomy_store_contract(lambda: RedisTaxonomyStore(FakeRedis()))


async def test_namespaces_are_isolated():
    client = FakeRedis()
    a = RedisTaxonomyStore(client, namespace="t:a")
    b = RedisTaxonomyStore(client, namespace="t:b")
    await a.promote("x")
    assert await a.is_known("x") is True
    assert await b.is_known("x") is False


def test_core_import_does_not_require_redis():
    # importing the top-level package must never pull in redis or contrib.
    # run in a clean subprocess so other test modules that imported contrib
    # cannot mask the regression via a warm sys.modules.
    import subprocess
    import sys

    code = (
        "import sys, labjury; "
        "assert 'labjury.contrib' not in sys.modules, 'core imported contrib'; "
        "assert 'redis' not in sys.modules, 'core imported redis'"
    )
    env = {**os.environ, "PYTHONPATH": "src"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


@pytest.mark.skipif(
    not os.environ.get("LABJURY_REDIS_URL"),
    reason="set LABJURY_REDIS_URL to run the real-Redis integration test",
)
async def test_real_redis_satisfies_contract():
    import uuid

    import redis.asyncio as aioredis

    client = aioredis.from_url(os.environ["LABJURY_REDIS_URL"], decode_responses=True)
    ns = f"labjury:test:{uuid.uuid4().hex}"
    try:
        await assert_taxonomy_store_contract(
            lambda: RedisTaxonomyStore(client, namespace=ns)
        )
    finally:
        keys = await client.keys(f"{ns}*")
        if keys:
            await client.delete(*keys)
        await client.aclose()
