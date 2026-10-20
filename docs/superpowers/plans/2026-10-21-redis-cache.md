# RedisCache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a durable Redis `Cache` reference backend — `labjury.contrib.redis_cache.RedisCache` (DI async client, optional TTL, `redis` extra, direct import) — plus the symmetric `labjury.audit.verdict_from_dict` it serializes through, with docs; no core behavior change.

**Architecture:** `verdict_from_dict` (inverse of the existing `verdict_to_dict`) lands in `labjury.audit`, the domain-serialization home. `RedisCache` round-trips a `Verdict` through `json`+those helpers against a dependency-injected async Redis client, namespacing keys and honoring an optional TTL. It mirrors `RedisTaxonomyStore`: `redis` extra, used by direct import, not re-exported, not entry-pointed. Tested against a fake async client (deterministic, no server) plus an opt-in live test.

**Tech Stack:** Python 3.11+ (pure stdlib `json` for the tested core); `redis` behind the existing extra; pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-redis-cache-design.md`

## Global Constraints

- Core `dependencies = []`; redis dep only in the existing `redis` extra; core never imports contrib.
- Serialization in `labjury.audit`, symmetric with existing `*_to_dict`/`*_from_dict`.
- `RedisCache`: DI client, direct import, not re-exported, not entry-pointed (needs a client arg) — the established ruling.
- No `Cache` conformance suite (YAGNI until a 2nd backend), no eviction beyond optional TTL, no core behavior change.
- TDD throughout; commit per task.

## Review Focus

- `verdict_from_dict(verdict_to_dict(v)) == v` — pinned in Task 1 (`test_verdict_roundtrip`).
- `put` then `get` returns an equal `Verdict` — pinned in Task 2 (`test_put_get_roundtrip`).
- `get` miss → `None` — pinned in Task 2 (`test_get_miss`).
- Keys namespaced; `ttl_s` passed as `ex` — pinned in Task 2 (`test_namespacing`, `test_ttl_passthrough`).
- `RedisCache` is a structural `Cache` — pinned in Task 2 (`test_is_a_cache`).

---

### Task 1: `verdict_from_dict` (symmetric serialization)

**Files:**
- Modify: `src/labjury/audit.py` (add `verdict_from_dict`)
- Test: `tests/test_audit.py` (add a round-trip case)

**Interfaces:**
- Consumes: `Action`, `Verdict` from `labjury.results`; the existing `verdict_to_dict`.
- Produces: `labjury.audit.verdict_from_dict(d: dict) -> Verdict` = `Verdict(Action(d["action"]), list(d["labels"]), dict(d["scores"]), list(d["novel_labels"]), d["reason"])`.

- [ ] **Step 1: Write the failing test** in `tests/test_audit.py`

```python
def test_verdict_roundtrip():
    from labjury.audit import verdict_from_dict, verdict_to_dict
    from labjury.results import Action, Verdict
    v = Verdict(Action.BLOCK, ["nsfw"], {"nsfw": 0.9}, ["novel"], "bad")
    assert verdict_from_dict(verdict_to_dict(v)) == v
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_audit.py -k verdict_roundtrip -v`
Expected: FAIL — `cannot import name 'verdict_from_dict'`.

- [ ] **Step 3: Implement `verdict_from_dict` in `src/labjury/audit.py`**

Place beside `verdict_to_dict`. `Action` is importable from `labjury.results` (add to the existing import if not already present).

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_audit.py -k verdict_roundtrip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/labjury/audit.py tests/test_audit.py
git commit -m "feat: verdict_from_dict — symmetric Verdict deserialization in audit"
```

---

### Task 2: `RedisCache` backend

**Files:**
- Create: `src/labjury/contrib/redis_cache.py`
- Test: `tests/test_redis_cache.py`

**Interfaces:**
- Consumes: `verdict_to_dict`/`verdict_from_dict` (Task 1); `Verdict`/`Action` from `labjury.results`; the `Cache` protocol (for the isinstance check); a duck-typed async client with `get(key)`/`set(key, value, ex=None)`.
- Produces: `labjury.contrib.redis_cache.RedisCache(client, namespace="labjury:cache", ttl_s=None)` with `async get(key) -> Verdict | None` and `async put(key, verdict) -> None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_redis_cache.py`

```python
import pytest

from labjury.contrib.redis_cache import RedisCache
from labjury.plugins import Cache
from labjury.results import Action, Verdict


class _FakeRedis:
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
    assert r.ex["labjury:cache:k1".replace("labjury:cache", "ns") if False else "ns:k1"] if False else r.ex["ns:k1" if False else next(iter(r.ex))] == 60


def test_is_a_cache():
    assert isinstance(RedisCache(_FakeRedis()), Cache)
```

(Keep `test_ttl_passthrough` simple — assert the stored key's `ex` is `60`; use the default namespace key `"labjury:cache:k1"`.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_redis_cache.py -v`
Expected: FAIL — `No module named 'labjury.contrib.redis_cache'`.

- [ ] **Step 3: Implement `src/labjury/contrib/redis_cache.py`**

`RedisCache` per Interfaces: `_key(key) = f"{namespace}:{key}"`; `put` does `set(_key, json.dumps(verdict_to_dict(verdict)), ex=ttl_s)` (pass `ex=self._ttl` — `None` is accepted by redis-py as "no expiry"); `get` reads, returns `None` on miss else `verdict_from_dict(json.loads(raw))`. Module docstring: `redis` extra, DI client, direct import.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_redis_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite** (+ confirm core import needs no redis)

Run: `pytest` and `PYTHONPATH=src python -c "import labjury"`
Expected: PASS; import works with no redis installed.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/contrib/redis_cache.py tests/test_redis_cache.py
git commit -m "feat: RedisCache — durable Cache reference backend (DI client, optional TTL)"
```

---

### Task 3: Docs

**Files:**
- Create: `docs/cache-backends.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `RedisCache` (Task 2).

- [ ] **Step 1: Write `docs/cache-backends.md`**

The `Cache` protocol (`get`/`put` over `str -> Verdict`); the serialization seam (`verdict_to_dict`/`verdict_from_dict`); `RedisCache` quickstart (`pip install labjury[redis]`, inject an async client, optional `ttl_s`); bring-your-own (any `str->Verdict` store, direct import, DI client — not entry-pointed); and the note that `InMemoryCache` is the zero-dep default. No new public top-level export.

- [ ] **Step 2: Add README pointers**

In the durable-backends area of `README.md` ("### Durable & custom taxonomy backends") add a sentence pointing to `docs/cache-backends.md` for a durable cache (`labjury.contrib.redis_cache.RedisCache`); mirror in `README.vi.md`.

- [ ] **Step 3: Run the full suite**

Run: `pytest`
Expected: PASS (docs-only; no code change).

- [ ] **Step 4: Commit**

```bash
git add docs/cache-backends.md README.md README.vi.md
git commit -m "docs: cache backends — RedisCache + bring-your-own"
```
