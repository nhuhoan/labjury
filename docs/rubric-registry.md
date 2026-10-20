# Rubric registry — versioned `label → Question`

A **rubric** is the question — the criteria — asked about a label. For the label
`violence`, a rubric might be the `Question` *"Does this contain graphic
violence?"* with its answer scale. The scorer (Jev, an LLM judge) answers the
rubric's question; the policy turns the answer into a verdict.

By default a proposer builds that question **inline**, in its own code:

```python
Candidate("violence", "violation", NoulQuestion("violence", "graphic violence?"))
```

That works, but for an enterprise it leaves three gaps:

1. **No single source of truth** — "what we ask about `violence`" is scattered
   across proposers, and two proposers can drift apart.
2. **No version identity** — when a compliance team rewords a rubric, nothing
   records *which* wording a past decision used.
3. **No reproducibility handle** — you cannot ask "show every decision made under
   rubric `violence@v1`," or reconstruct the exact rubric a March decision used.

The rubric registry is the opt-in mechanism that closes those gaps. As with
everything in LabJury, **the framework owns the registry, not the rubric
content**: what the questions say, how versions are named, and the law/policy
behind them stay yours.

## The seam

A `Rubric` is an immutable `(label, question, version)`. A `RubricStore` persists
and versions them:

```python
class RubricStore(Protocol):
    async def register(self, label: str, question: Question, version: str) -> Rubric
    async def resolve(self, label: str) -> Rubric | None     # the current rubric
    async def get(self, label: str, version: str) -> Rubric | None   # a historical one
    async def history(self, label: str) -> list[str]         # versions, in order
```

- **`register`** publishes a version and makes it current. Re-publishing the same
  `(label, version)` with the **same** question is idempotent; with a **different**
  question it raises `ValueError` — **a published version is immutable**, which is
  exactly what makes it a reliable reproducibility handle.
- **`resolve`** returns the most recently registered rubric for a label (or `None`).
- **`get`** returns one specific version even after it's been superseded — the
  reproducibility read.
- **`history`** lists a label's versions in registration order.

`InMemoryRubricStore` is the zero-dependency reference backend, re-exported from
the top level:

```python
import labjury as lj

store = lj.InMemoryRubricStore()
await store.register("violence", NoulQuestion("violence", "graphic violence?"), "v1")
await store.register("violence", NoulQuestion("violence", "depicts real-world graphic violence?"), "2024-gdpr")

(await store.resolve("violence")).version          # "2024-gdpr"  (current)
(await store.get("violence", "v1")).question       # the original v1 wording, still there
await store.history("violence")                    # ["v1", "2024-gdpr"]
```

## Sourcing a question from the registry

A proposer consults the registry instead of hard-coding the question, and records
the version on the candidate:

```python
r = await store.resolve(label)
Candidate(label, "violation", r.question, rubric_version=r.version)
```

Nothing forces this — the `Proposer` and `Candidate` contracts are unchanged, and
the engine does not wire a registry in. Adding a `RubricStore` to your proposers
is deployer code.

## The reproducibility link

`Candidate` carries an optional `rubric_version: str | None` (default `None`). The
engine already serializes every candidate into its `AuditEvent`, so the version
rides into whatever audit store you plug in — **with no engine change**. A recorded
decision therefore answers "which rubric revision produced this candidate," and
`get(label, version)` reconstructs the exact rubric that was in force:

```
decision audit event → candidate.rubric_version = "v1"
                         └── store.get("violence", "v1") → the exact Question asked
```

Candidates built the old way (no `rubric_version`) decode to `None`, so audit
records from before you adopted the registry keep working.

## Bring your own backend

Like taxonomy and audit backends, a durable `RubricStore` (Redis, SQLite,
Postgres, a config repo) is yours to implement — LabJury ships no fixed storage.
Prove a backend is a drop-in with the in-package conformance suite:

```python
from labjury.testing import assert_rubric_store_contract

await assert_rubric_store_contract(MyRubricStore)   # zero-arg factory, sync or async
```

The suite asserts only the universal invariants: empty reads on an unregistered
label, `resolve` returning the latest version, `get` surviving supersession,
history order, and the immutability of a published version. A durable reference
backend is a near-trivial variant of `InMemoryRubricStore` (same four methods over
a table or key space) and may ship under `labjury.contrib` later.

## Non-goals

- **No engine auto-wiring** — the engine stays rubric-agnostic; it serializes
  whatever `Candidate` it is handed.
- **No built-in rubrics and no judgment of rubric content** — LabJury does not know
  what a "good" question is; that is your policy/compliance domain.
- **No deletion or mutation of a published version** — the registry only adds, the
  same immutability stance as the audit log.
- **No fixed storage** — `InMemoryRubricStore` is a reference, not a production
  store.
