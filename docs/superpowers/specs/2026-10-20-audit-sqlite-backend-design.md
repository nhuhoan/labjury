# SQLite audit-log reference backend — design

**Date:** 2026-10-20
**Tier / step:** Enterprise readiness — Tier 1, step 2b
**Depends on:** step 2a (storage-agnostic audit trail — the `AuditLog` protocol
and the `AuditEvent.to_dict`/`from_dict` seam).

## Intent and the why

Step 2a shipped the audit trail with **no database** on purpose: the core
defines the append-only `AuditLog` protocol, ships `NullAuditLog` (opt-out) and
`InMemoryAuditLog` (ephemeral), and exposes the `AuditEvent.to_dict`/`from_dict`
serialization seam so any company can persist events into their own store
(Kafka, S3, a SIEM, Postgres). What it did *not* ship is proof that the protocol
is implementable against a **real durable store**, nor a runnable starting point
a stranger can copy.

This step ships exactly one such reference backend: `SqliteAuditLog`. Its job is
twofold — (a) prove the `AuditLog` contract holds against a store that **survives
process restart**, and (b) give a company a working, copyable example. It is
mirror-for-mirror the same move step 1 made with `RedisTaxonomyStore`.

## This does NOT make LabJury depend on a database

The standing constraint — *the framework depends on no fixed database* — is
about the **core**, and it is untouched here. `SqliteAuditLog` lives in
`labjury.contrib.*`, the core never imports it, and nothing in the default
install pulls it in. It is one optional example among infinitely many, exactly
like `RedisTaxonomyStore`. A company is free to ignore it and back the audit log
with their own store via the same protocol. (This question was raised explicitly
during brainstorming; the answer is the two-tier distinction: core depends on
nothing; contrib ships runnable examples.)

## Why SQLite (CTO call, flagged for veto)

The deferred choice was SQLite vs Postgres. **SQLite**, via the Python stdlib
`sqlite3` module wrapped in `asyncio.to_thread`:

1. **A reference backend must run in a stranger's CI with zero infrastructure.**
   SQLite is a file on disk — durable, survives restart, no server. Postgres
   needs a running server (or testcontainers), making both our CI and the user's
   heavier and flakier. A reference that can't run dep-free fails at being a
   reference.
2. **Zero new dependency.** `sqlite3` is stdlib. Wrapped in `asyncio.to_thread`
   it honors the async protocol without blocking the event loop and without
   adding a single package. This is maximally aligned with the zero-dependency
   core ethos.
3. **Postgres is a near-trivial variant once the shape is proven** — same SQL,
   same `to_dict`/`from_dict` seam, same `by_correlation` query; swap the driver.
   We prove the hard parts (append-only schema, insertion-order retrieval,
   round-trip through the serialization seam) once.

Redis (already shipped for taxonomy) was rejected for audit: it is memory-first,
and an audit trail is precisely the artifact a company must retain long-term for
compliance — wrong durability profile.

## Goals

- One class, `SqliteAuditLog`, in `labjury.contrib.sqlite_audit`, satisfying the
  `AuditLog` protocol.
- Passes the shipped `assert_audit_log_contract` conformance suite unmodified.
- **Durability is proven by test**: events recorded by one instance are read
  back by a *fresh* instance opened on the same file after the first is dropped.
- Full-fidelity round-trip: an `AuditEvent` with every field populated survives
  storage and retrieval unchanged, through the `to_dict`/`from_dict` seam only.
- Zero new dependency; no new install extra.

## Non-goals

- No Postgres / MySQL / other backend in this step (left as the documented
  near-trivial variant).
- No retention/rotation/pruning policy — append-only is the whole point; the
  deployer owns lifecycle.
- No query API beyond the protocol's `by_correlation` (no "all events since T",
  no full-text search). A real SIEM owns richer querying.
- No connection injection / pooling knobs — SQLite is a single file, not a
  networked server (see below).

## Anti-goals (would make this a failure even if it worked)

- Making the core import `sqlite3` or `labjury.contrib` — the core stays empty.
- Presenting SQLite as *the* audit store rather than *an example* — docs must
  keep "bring your own storage" primary.
- A backend that silently loses or reorders events under concurrent writes.

## The how — decided

**Module / class:** `src/labjury/contrib/sqlite_audit.py`, class `SqliteAuditLog`.

**Constructor — path-owned, not connection-injected (deviates from step 1's DI
style, deliberately):** `SqliteAuditLog(path: str, table: str = "labjury_audit")`.
Step 1 injected the Redis *client* because a networked store's pooling/TLS/
failover belong to the deployer. SQLite has none of that: it is a local file.
Injecting a live `sqlite3.Connection` would be actively wrong here, because
`sqlite3` connections carry **thread affinity** (`check_same_thread`) and we
dispatch work onto arbitrary `asyncio.to_thread` pool threads. So the backend
owns the file path and opens a **short-lived connection per operation inside the
thread call** — sidestepping thread-affinity entirely and letting SQLite's own
file locking serialize concurrent access. `table` lets independent logs share a
file, mirroring Redis's `namespace`.

**Async discipline:** every blocking `sqlite3` call runs under
`asyncio.to_thread` so the event loop is never blocked. Schema creation happens
once, synchronously, in `__init__` (a one-time setup on the caller's thread).

**Schema (append-only, one table):**
```sql
CREATE TABLE IF NOT EXISTS <table> (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,  -- insertion order
    event_id       TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload        TEXT NOT NULL                        -- json.dumps(event.to_dict())
);
CREATE INDEX IF NOT EXISTS <table>_corr ON <table> (correlation_id);
```
- `seq AUTOINCREMENT` gives the contract's required **insertion order** for
  `by_correlation`.
- `payload` stores `json.dumps(event.to_dict())`; reads do
  `AuditEvent.from_dict(json.loads(payload))`. The backend touches **only** the
  serialization seam, never LabJury's internal types.
- `PRAGMA journal_mode=WAL` set once at init for better concurrent read/write;
  connections open with `timeout=30` so a writer waits on the lock rather than
  erroring with "database is locked".

**Methods (the whole protocol, nothing more):**
```python
async def record(self, event: AuditEvent) -> None:
    # INSERT INTO <table> (event_id, correlation_id, payload) VALUES (?, ?, ?)
async def by_correlation(self, correlation_id: str) -> list[AuditEvent]:
    # SELECT payload FROM <table> WHERE correlation_id = ? ORDER BY seq
    # -> [AuditEvent.from_dict(json.loads(p)) for p in rows]
```
No `update`, no `delete` — the conformance suite asserts the type lacks both;
immutability is the point of an audit trail.

**Not entry-point registered** (consistent with step 1's ruling): the registry
calls zero-argument factories, and `SqliteAuditLog` needs a `path`. It is used by
direct import, like `RedisTaxonomyStore` and `LLMJudgeScorer`. The
`labjury.audit_logs` entry-point group remains the documented contract for
zero-arg third-party backends.

**Not re-exported from top-level `labjury`** (consistent with `RedisTaxonomyStore`):
imported via `from labjury.contrib.sqlite_audit import SqliteAuditLog`, keeping
the core namespace free of contrib and the core `__init__` free of contrib
imports.

## What's left to the builder

- Exact SQL text and the `asyncio.to_thread` wrapping per method.
- Test file `tests/test_sqlite_audit.py`: (1) conformance via
  `assert_audit_log_contract` against a fresh temp-file store; (2) the
  **durability** test — record, drop the instance, reopen on the same path, read
  back; (3) the **full-fidelity round-trip** test — every `AuditEvent` field
  populated, stored, reopened, compared equal. No core-import-isolation test is
  needed; the existing subprocess test in `tests/test_redis_taxonomy.py` already
  asserts the top-level package pulls in neither `contrib` nor its deps.
- Docs: extend `docs/audit-trail.md` with a short "SQLite reference backend"
  subsection beside the existing JSONL example (no new file — audit-trail.md is
  the audit home); a one-line pointer in `README.md` and `README.vi.md`.

## Builder check

Per the brainstorming skill a fresh builder should sanity-read this. Honoring
the standing no-spawn-without-asking constraint, this is a self builder-check,
not an independent subagent — weaker, and noted as such. Open question a builder
would raise and its settled answer: *"Can the conformance factory be called more
than once on the same path?"* — `assert_audit_log_contract` calls the factory
once; the test supplies a unique temp path per test via `tmp_path`, so no
cross-test bleed. Settled; recorded here.
