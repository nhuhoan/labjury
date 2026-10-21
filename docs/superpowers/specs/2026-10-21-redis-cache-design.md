# RedisCache — a durable Cache reference backend

**Status:** design (CTO-decided; owner delegated, chose "reference plugins") — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap — reference plugins. The one cleanly buildable-and-testable reference backend in this sandbox (Jev scorer / VN proposer / ASR-OCR builders need external services/models → scaffold + doc only, not this slice).

## Intent and the why

The `Cache` protocol (`async get(key) -> Verdict | None`, `async put(key, verdict)`)
has only the in-memory `InMemoryCache`. A deployment that wants verdict caching to
survive restarts and be shared across workers needs a durable backend. LabJury ships
a **reference** Redis cache — same "bring your own storage" story as the taxonomy and
audit backends: a dependency-injected async client (the deployer owns pooling, TLS,
failover), behind the existing `redis` extra, used by direct import.

Caching a `Verdict` requires serializing it. `labjury.audit.verdict_to_dict` already
encodes a `Verdict`; this slice adds its symmetric `verdict_from_dict` (the audit
module is the home of domain-object serialization), and `RedisCache` round-trips
through JSON.

## Goals

- **`labjury.audit.verdict_from_dict(d: dict) -> Verdict`** — the inverse of
  `verdict_to_dict`: `Verdict(Action(d["action"]), d["labels"], d["scores"],
  d["novel_labels"], d["reason"])`.
- **`labjury.contrib.redis_cache.RedisCache(client, namespace="labjury:cache", ttl_s=None)`**:
  - `async get(key) -> Verdict | None` — `GET namespace:key`; `None` on miss; else
    `verdict_from_dict(json.loads(raw))`.
  - `async put(key, verdict) -> None` — `SET namespace:key json.dumps(verdict_to_dict(verdict))`,
    with `ex=ttl_s` when `ttl_s is not None` (optional expiry for verdicts).
  - DI async client (never created here); `redis` extra; used by direct import,
    **not** re-exported top-level and **not** entry-pointed (needs a client arg) —
    consistent with `RedisTaxonomyStore`.
- **Docs:** `docs/cache-backends.md` (the `Cache` contract, the serialization seam,
  the Redis quickstart, bring-your-own) + a README pointer in the durable-backends area.

## Non-goals / anti-goals

- **No new dependency / no new extra** — reuses the existing `redis` extra.
- **No top-level re-export, no entry-point** — DI-style backend, direct import only
  (the established ruling for client-injecting backends).
- **No `Cache` conformance suite in this slice** — `RedisCache` is proven behaviorally
  against a fake async client here; a reusable `assert_cache_contract` is a possible
  tiny follow-on, not required until a second cache backend exists (YAGNI).
- **No cache invalidation/eviction policy beyond optional TTL**, no tag/bulk ops —
  the protocol is get/put; richer ops are the deployer's.
- **No core behavior change** — `verdict_from_dict` is an additive serialization
  helper; the engine and `Cache` protocol are untouched.

## Constraints (inherited)

- Core `dependencies = []`; the redis dep lives only in the `redis` extra;
  `labjury.contrib.redis_cache` is only imported when the deployer imports it. Core
  never imports contrib.
- Serialization lives in `labjury.audit` (the domain-serialization home), symmetric
  with the existing `*_to_dict`/`*_from_dict` pairs.
- Python 3.11+. TDD throughout; commit per task.

## The parts of the how, as decided

- **Why a TTL option:** moderation verdicts are often safe to expire (content or policy
  changes); an optional `ex` is a one-parameter, high-value affordance. Default `None`
  = no expiry (matches `InMemoryCache`).
- **Why test against a fake client:** a tiny in-memory async `get`/`set(ex=)` fake makes
  the serialization + key-namespacing + TTL-passthrough logic deterministic and
  runnable here, without a live server. An opt-in live test (via `LABJURY_REDIS_URL`)
  mirrors the taxonomy backend's integration test and is skipped by default.

## What's left to the builder

- The fake async Redis client used in tests (`get`/`set` with an `ex` kwarg over a dict).
- Exact namespace separator (`:`), matching `RedisTaxonomyStore`.

## Review focus (inputs the tests must pin)

- **`verdict_from_dict(verdict_to_dict(v)) == v`** for a full verdict (action enum,
  labels, scores, novel_labels, reason) — Task 1.
- **`put` then `get` returns an equal `Verdict`** (round-trips through JSON) — Task 2.
- **`get` on a missing key returns `None`** — Task 2.
- **Keys are namespaced** (`namespace:key`) and **`ttl_s` is passed as `ex`** on `put`
  when set — Task 2.
- **`RedisCache` is a structural `Cache`** (`isinstance`) — Task 2.
