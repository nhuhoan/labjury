# Durable TaxonomyStore (Redis) — design

Date: 2026-10-20
Status: proposed (Tier 1, step 1 of the enterprise-readiness roadmap)
Author's note: decisions below are **my (CTO) calls** under the owner's
"you decide" delegation, not choices the owner signed off on individually.
The owner's checkpoint is the implementation plan that follows this doc.

## Intent & why

LabJury's default `InMemoryTaxonomyStore` loses the entire learned
vocabulary on restart. No large company will run an open-world labeling
system whose "what labels are official" state is volatile. This step gives
the taxonomy a durable backend so the `propose → novel → promote` lifecycle
survives process restarts and is shared across workers.

This is step 1 of Tier 1. It is deliberately the first brick because it is
self-contained, it is the foundation the audit trail (step 2) builds on, and
it is the cheapest honest test that the plugin boundary holds under real I/O.

It also establishes the **convention for every dependency-carrying reference
plugin** that the later tiers will add (Postgres audit store, OTel exporter,
etc.), so the packaging rules here are load-bearing beyond this one class.

**The real deliverable is the contract, not Redis.** A large company may
reject Redis and back the taxonomy with their own system (Cassandra,
DynamoDB, Postgres, an in-house KV). They must be able to do that by writing
a class that satisfies the `TaxonomyStore` protocol and registering it —
**with no change to core** — exactly as "Jev is just one Scorer." So the
primary output of this step is a *proven, verifiable durable-backend
contract*: the protocol, a reusable conformance test suite anyone can run
against their own backend, and a "bring your own backend" doc. Redis is the
reference implementation that proves the contract and ships a batteries-
included option; it is a consequence, not the point.

## Goals

- **A reusable conformance test suite** (`taxonomy_store_contract`) that takes
  any `TaxonomyStore` factory and asserts every open-world invariant. It is a
  first-class, importable test artifact so a third party building their own
  backend runs the *same* suite to prove drop-in equivalence.
- **A "write your own TaxonomyStore" doc** showing the protocol, the
  no-inheritance/no-core-change rule, entry-point registration, and how to run
  the conformance suite against a custom backend.
- A `RedisTaxonomyStore` reference implementation that is a drop-in
  `TaxonomyStore`, behaviorally identical to `InMemoryTaxonomyStore` (two-tier
  official/proposed, open-world `is_known` only-after-promote), and that passes
  the conformance suite.
- Core stays **zero-dependency**. Redis is an opt-in extra: `pip install
  labjury[redis]`.
- Durable across restarts; safe for concurrent workers (promote is atomic).
- Discoverable via the existing `labjury.taxonomies` entry-point group.
- Unit-testable with **no new runtime or test dependency** and without a
  running Redis.

## Non-goals

- Multi-tenancy itself (Tier 2). But a `namespace` key-prefix is included now
  because it is nearly free and forward-compatible.
- The audit trail (Tier 1, step 2) — separate step, likely Postgres.
- Caching backend (`Cache`) — separate step; same convention will apply.
- Any change to engine/policy/router logic.

## Anti-goals (would make this a failure even if it "works")

- Adding `redis` to core `dependencies`. Core must still import and run with
  zero third-party packages.
- Core code importing anything under the new `contrib` namespace.
- The Redis store managing connection lifecycle (opening sockets, pools)
  itself — that couples it to deployment and breaks dependency injection.

## Decisions (the "how")

1. **Backend: Redis first** (not Postgres). The taxonomy is small, read-heavy,
   set-membership state. Redis sets map exactly: `SISMEMBER`/`SADD`/`SMEMBERS`,
   and `SMOVE` makes `promote` a single atomic op. The design already named
   Redis as the reference taxonomy backend. Postgres is the right tool for the
   *audit trail* (relational, queryable history) — different step, different
   tool.

2. **Packaging: optional extra in the same dist, under a sanctioned
   `contrib` namespace.** Code lives at `src/labjury/contrib/redis_taxonomy.py`.
   New extra `redis = ["redis>=5"]`. Rule, documented and enforced by
   convention: **`labjury.contrib.*` may carry extra dependencies; core never
   imports `contrib`.** This keeps one repo / one release cadence while
   preserving `dependencies = []`. (A fully separate `labjury-redis` dist was
   considered and rejected as premature overhead for a v0.0.x project.)

3. **Dependency injection of the client.** Constructor takes an already-created
   `redis.asyncio` client plus an optional `namespace` prefix:
   `RedisTaxonomyStore(client, namespace="labjury:tax")`. The store issues
   commands; it never creates or owns the connection. Mirrors the
   `LLMJudgeScorer(chat=...)` DI style already in the codebase. Enables fakes
   in tests and lets deployers own pooling/TLS/failover.

4. **Key layout.**
   - `{namespace}:official` — Redis set of promoted labels.
   - `{namespace}:proposed` — Redis set of proposed-but-not-promoted labels.
   Operations: `is_known` = `SISMEMBER official`; `propose` = `SADD proposed`
   (guarded so an already-official label is not re-proposed); `promote` =
   `SMOVE proposed official` then `SADD official` (so promoting a never-proposed
   label still works); `known_labels` = `SMEMBERS official`; `proposed_labels` =
   `SMEMBERS proposed`. **`meta` is accepted but not persisted in this step** —
   nothing reads it yet (YAGNI); meta persistence lands with the audit-trail
   step (Tier 1, step 2) that will actually read it. This keeps the fake client
   down to four commands (`sismember`, `sadd`, `smembers`, `smove`).

5. **Protocol extension (additive).** Promote `promote` and `proposed_labels`
   from `InMemoryTaxonomyStore`-only methods into the `TaxonomyStore` Protocol,
   so the open-world lifecycle is a first-class, documented contract that every
   backend must honor. This is additive (the in-memory store already satisfies
   it); the contract is young (v0.0.1) so formalizing it now is cheap and
   correct per the OSS clean-contract principle.

6. **Entry point.** ~~Register under `labjury.taxonomies`.~~ **Superseded during
   implementation (see plan ledger ruling):** the registry instantiates entry
   points with a *zero-arg* `factory()`, but `RedisTaxonomyStore` requires an
   injected `client`. So — exactly like `LLMJudgeScorer`, which needs an
   injected `chat` and is also not entry-pointed — it is used by **direct
   import** (`from labjury.contrib.redis_taxonomy import RedisTaxonomyStore`).
   The `labjury.taxonomies` group remains the extension point for third-party
   *zero-arg-constructible* taxonomies.

## Testing strategy ("làm chắc")

The **conformance suite is the backbone**, not an afterthought:

- **Conformance suite** — a reusable set of behavioral assertions exposed as an
  importable helper (e.g. `labjury.testing.taxonomy_store_contract`) that takes
  a `make_store` factory and drives one store instance through every open-world
  invariant: `is_known` is false until `promote`; proposing an already-official
  label is a no-op; `propose` then `promote` makes it known; `promote` moves
  proposed→official (and is safe when the label was never proposed);
  `proposed_labels`/`known_labels` reflect the two tiers. It carries no backend
  assumptions. `meta` persistence is **not** in the contract at all this step
  (no backend persists it yet).
- **Both built-in stores run the suite.** `InMemoryTaxonomyStore` and
  `RedisTaxonomyStore` are each parametrized through the same suite, which is
  what *proves* drop-in equivalence (the thing a company swapping backends
  relies on). This supersedes the earlier "noted, not required" stance.
- **Redis unit tests** run the suite against `RedisTaxonomyStore` backed by a
  tiny hand-rolled in-memory fake async client implementing only the four
  commands used (`sismember`, `sadd`, `smembers`, `smove`). No `fakeredis`, no
  new dependency.
- **One optional integration test** runs the suite against a real Redis,
  `skipif` the `LABJURY_REDIS_URL` env var is absent, so CI/dev without Redis
  stays green.
- The suite ships as a supported artifact precisely so a third party building
  their own `TaxonomyStore` imports it and runs it against their backend — the
  "làm chắc" guarantee extends to bring-your-own backends, not just ours.

## Left to the builder (plan/implementation)

- Exact fake-client shape and where it lives (test util).
- The exact import path / module for the conformance suite helper (default:
  `labjury.testing`), and whether it is exported at top level. It must be
  importable by third parties, so it lives in the shipped package, not under
  `tests/`.
- Docstrings / README note for `pip install labjury[redis]` and a usage snippet,
  plus the "write your own TaxonomyStore" doc (protocol + conformance-suite usage).
- Whether `RedisTaxonomyStore` is exported from the top-level `labjury`
  package. Default: **no** — contrib backends are imported from their module
  (`from labjury.contrib.redis_taxonomy import RedisTaxonomyStore`) so the
  zero-dep top-level import never touches `redis`.
