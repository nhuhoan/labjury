# Audit trail — record, explain, replay

Large-scale moderation needs more than a verdict: when a decision is appealed,
audited, or debugged, you must be able to pull up *that exact decision* and
reproduce how it was reached. LabJury records one immutable `AuditEvent` per
decision and can replay the decision policy from it.

Auditing is **opt-in** (default: a no-op) and **storage-agnostic** — LabJury
ships no database. You bring your own store.

## What a decision records

Pass any `AuditLog` to the engine:

```python
import labjury as lj

audit = lj.InMemoryAuditLog()
engine = lj.Engine(..., audit=audit)

await engine.process(lj.Item("item-42", {"text": "…"}))
[event] = await audit.by_correlation("item-42")
```

Each `AuditEvent` carries: `correlation_id`, `input_fingerprint` (a hash — the
**raw content is never stored**), `modalities`, `used_proposer`, the
`candidates` and the scorer's `answers`, the taxonomy's official `known_labels`
at decision time, `provenance` (scorer and policy name/version/params), and the
`verdict`. A cache-served decision records a thin event with `from_cache=True`.

A failing audit backend never breaks a decision — recording is best-effort; the
backend owns its own durability and retry.

## Replaying a decision

```python
from labjury import replay_decision, verdict_matches, RecallBiasedPolicy

verdict = await replay_decision(event, RecallBiasedPolicy())
assert verdict_matches(event, verdict)
```

Replay re-runs the **decision policy** over the recorded candidates, answers,
and taxonomy snapshot — it does *not* re-call the scorer/LLM (those outputs are
recorded, not reproduced). So you can explain *why* a verdict happened, and test
what a policy change would have done to historical decisions. Replaying a
`from_cache` event raises `ValueError` — replay the original decision's event.

For a one-line *verification* — did the verdict reproduce, and has the policy
version drifted since? — use `verify_replay`, which composes replay with a version
diff into a `ReplayReport`. See [reproducibility.md](reproducibility.md).

## Bring your own storage

LabJury ships **no database backend** on purpose: every company has its own
store (Kafka, S3, a SIEM, Postgres, SQLite). An audit backend is any object
satisfying the append-only `AuditLog` protocol — no inheritance, no core change:

```python
async def record(self, event: AuditEvent) -> None: ...
async def by_correlation(self, correlation_id: str) -> list[AuditEvent]: ...
```

Persist and reload through the serialization seam — plain JSON-native dicts, so
your backend never touches LabJury's internal types:

```python
row = event.to_dict()            # JSON-native; store it anywhere
event = AuditEvent.from_dict(row)  # exact round-trip
```

Prove your backend conforms with the shipped suite:

```python
from labjury.testing import assert_audit_log_contract

async def test_my_audit_log():
    await assert_audit_log_contract(lambda: MyAuditLog(fresh_store()))
```

A minimal file-backed example:

```python
import json
from labjury import AuditEvent

class JsonlAuditLog:
    def __init__(self, path):
        self._path = path

    async def record(self, event):
        with open(self._path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    async def by_correlation(self, correlation_id):
        out = []
        with open(self._path) as f:
            for line in f:
                e = AuditEvent.from_dict(json.loads(line))
                if e.correlation_id == correlation_id:
                    out.append(e)
        return out
```

The log is **append-only** by contract: `record` and reads only, never update
or delete — immutability is the point of an audit trail.

## The SQLite reference backend

If you want a durable store without standing up infrastructure, one ships
built-in — `SqliteAuditLog`, backed by the stdlib `sqlite3`. **No install
extra** (SQLite is in Python's standard library):

```python
from labjury.contrib.sqlite_audit import SqliteAuditLog

engine = lj.Engine(..., audit=SqliteAuditLog("audit.db"))
```

Events land in a single append-only table and **survive a restart** — a fresh
`SqliteAuditLog` opened on the same path reads back everything the last one
wrote. `table="labjury_audit"` lets independent logs share one file. The
blocking `sqlite3` calls run under `asyncio.to_thread`, so the backend honors
the async `AuditLog` protocol without stalling the event loop.

Like `RedisTaxonomyStore`, this is **one reference backend, not a requirement**.
A Postgres (or any SQL) backend is the same shape — the same append-only
schema, the same `to_dict`/`from_dict` seam, the same `by_correlation` query —
with a different driver. Prove yours with `assert_audit_log_contract`.
