# Cache backends

LabJury can cache a decision so an identical item isn't re-judged. The cache is
a plugin behind one small protocol — the engine never assumes where verdicts
live, so you bring your own store.

## The `Cache` protocol

```python
class Cache(Protocol):
    async def get(self, key: str) -> Verdict | None: ...
    async def put(self, key: str, verdict: Verdict) -> None: ...
```

`get` returns the cached `Verdict` for a key, or `None` on a miss; `put` stores
one. That's the whole contract — invalidation, eviction and bulk operations are
your store's concern, not the framework's.

The engine caches `ACCEPT` and `BLOCK` verdicts. It re-scores `REVIEW` decisions
for each item so the item's audit event has candidates and answers for human review.
The concurrency limit applies across simultaneous `process` and `process_batch`
calls on the same engine instance.

The zero-dependency default is `labjury.InMemoryCache` (a process-local dict):

```python
engine = lj.Engine(..., cache=lj.InMemoryCache())
```

## The serialization seam

Durable backends persist a `Verdict` as JSON through the audit module's seam:

```python
from labjury.audit import verdict_to_dict, verdict_from_dict

raw = json.dumps(verdict_to_dict(verdict))   # store
verdict = verdict_from_dict(json.loads(raw))  # load
```

These are symmetric: `verdict_from_dict(verdict_to_dict(v)) == v`. Backends touch
only this seam — they never need to understand LabJury's internal types.

## Redis reference backend

A Redis-backed cache ships built-in:

```bash
pip install labjury[redis]
```

```python
from labjury.contrib.redis_cache import RedisCache

engine = lj.Engine(..., cache=RedisCache(async_redis_client))
```

The async client is **injected, never created** — you own pooling, TLS and
failover. Options:

- `namespace` (default `"labjury:cache"`) — key prefix, so one Redis can hold
  several caches.
- `ttl_s` (default `None` = no expiry) — optional per-key TTL in seconds, passed
  straight through as Redis `EX`. Verdicts are often safe to expire as content
  or policy changes.

`RedisCache` is imported directly (like `RedisTaxonomyStore`); it is **not**
re-exported at the top level and **not** entry-pointed, because it needs a client
argument.

## Bring your own

Redis is just one option. Back the cache with anything that maps `str -> Verdict`
— Memcached, a CDN edge KV, Postgres, an in-house store — by implementing the two
`Cache` methods and round-tripping through the serialization seam above. Inject
your instance via `lj.Engine(..., cache=...)`.
