from labjury.contrib.redis_cache import RedisCache
from labjury.plugins import Cache
from labjury.results import Action, Verdict


class _FakeRedis:
    """Deterministic in-memory stand-in: async get/set over a dict, recording ex."""

    def __init__(self):
        self.store = {}
        self.ex = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.ex[key] = ex


def _v():
    return Verdict(Action.BLOCK, ["nsfw"], {"nsfw": 0.9}, [], "bad")


async def test_put_get_roundtrip():
    c = RedisCache(_FakeRedis())
    await c.put("k1", _v())
    assert await c.get("k1") == _v()


async def test_get_miss():
    assert await RedisCache(_FakeRedis()).get("nope") is None


async def test_namespacing():
    r = _FakeRedis()
    await RedisCache(r, namespace="ns").put("k1", _v())
    assert "ns:k1" in r.store


async def test_ttl_passthrough():
    r = _FakeRedis()
    await RedisCache(r, ttl_s=60).put("k1", _v())
    assert r.ex["labjury:cache:k1"] == 60


def test_is_a_cache():
    assert isinstance(RedisCache(_FakeRedis()), Cache)
