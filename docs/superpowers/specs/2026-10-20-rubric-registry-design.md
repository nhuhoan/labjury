# Rubric registry — a versioned, storage-agnostic `label → Question` seam

**Status:** design (CTO-decided; owner delegated design authority, approved 2026-10-20) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness **Tier 2** (operability at scale), **item 1 of 5** — the rubric registry. First Tier-2 slice; the natural sequel to the criteria model.

## Intent and the why

A *rubric* is the question — the criteria — asked about a label: for the label
`violence`, the `Question` "Does this contain graphic violence?" with its scale.
Today that `label → Question` mapping is **hard-coded inline inside each
proposer**: a proposer builds `Candidate(label, kind, question)` with the
question literal in its own code. Three consequences hurt enterprise operability:

1. **No single source of truth.** The wording of "what we ask about `violence`"
   is scattered across proposer implementations; two proposers can ask subtly
   different questions about the same label.
2. **No version identity.** When a compliance team rewords a rubric
   (v1 → "2024-gdpr"), nothing records *which* version a given decision used. The
   audit trail already stores the question text verbatim per decision, but there
   is no stable version handle to group or compare decisions by rubric revision.
3. **No reproducibility handle.** Replaying or explaining "why did item X get
   this verdict in March" needs the exact rubric then in force. Text is recorded;
   identity is not — so you cannot ask "show every decision made under rubric
   `violence@v1`."

This slice adds the **mechanism** to persist and version `label → Question`,
and threads a **version handle into the audit trail** so a decision records which
rubric revision produced its candidate. It is the foundation the rest of Tier 2
(reproducibility/versioning) builds on.

Same seam philosophy as all of Tier 1: **LabJury owns the registry mechanism, not
the rubric content.** What the questions say, how versions are named, and the
law/policy behind them is the deployer's domain. Core ships the protocol, a
zero-dep in-memory reference, and a conformance suite; durable backends are
bring-your-own.

## Goals

- **`Rubric` value object** (`labjury.rubrics.Rubric`): an immutable
  `(label: str, question: Question, version: str)` — a versioned rubric for one
  label.
- **`RubricStore` protocol** (`labjury.plugins.RubricStore`, `@runtime_checkable`),
  mirroring `TaxonomyStore`'s shape:
  - `async register(label: str, question: Question, version: str) -> Rubric` —
    store a versioned rubric for a label and make it the current one; returns the
    stored `Rubric`. Re-registering the **same** `(label, version)` with the same
    question is idempotent; re-using a version string for a *different* question
    is a `ValueError` (a version is immutable once published).
  - `async resolve(label: str) -> Rubric | None` — the **current** rubric for a
    label (the most recently registered), or `None` if the label has none.
  - `async get(label: str, version: str) -> Rubric | None` — a **specific**
    historical version, or `None`. This is the reproducibility read.
  - `async history(label: str) -> list[str]` — the version strings registered for
    a label, in registration order (empty if none).
- **`InMemoryRubricStore`** (`labjury.rubrics`): zero-dep reference backend; the
  current rubric is the last registered version per label.
- **`assert_rubric_store_contract(make_store)`** in `labjury.testing`: in-package
  conformance suite proving any backend honors the universal invariants.
- **Reproducibility link, non-breaking:** add an optional field
  `Candidate.rubric_version: str | None = None` (dataclass default — existing
  proposers that build `Candidate(label, kind, question)` are unaffected). The
  engine already serializes candidates into the `AuditEvent` via
  `candidate_to_dict`; extend `candidate_to_dict` / `candidate_from_dict` to carry
  `rubric_version`. The version then rides into whatever audit store the deployer
  plugs in, with **no engine change and no `AuditEvent` schema method change**.
- **Public surface:** re-export `Rubric`, `RubricStore`, `InMemoryRubricStore`,
  `assert_rubric_store_contract` from `labjury`; add to `test_public_api.py`.
- **Docs:** `docs/rubric-registry.md` (protocol, invariants, versioning model, the
  audit/reproducibility link, bring-your-own-backend) + bilingual README pointers.

## Non-goals / anti-goals

- **No durable backend in this slice.** Redis/SQLite/Postgres rubric stores are
  left as the documented near-trivial variant (same move as Postgres at step 2b,
  OTel at step 3) — the protocol + conformance suite make them drop-in. Shipping
  one now would widen the slice past "chắc từng bước."
- **No change to the `Proposer` or `Scorer` contract.** A proposer *may* consult a
  `RubricStore` to source its questions; nothing forces it to, and the engine does
  not wire one in. Adding a registry to an engine/proposer is deployer code.
- **No auto-wiring in the `Engine`.** The engine stays rubric-agnostic: it
  serializes whatever `Candidate` it is handed. No new engine constructor arg.
- **No `DecisionPolicy` involvement.** Rubrics shape the *question asked*, not the
  *verdict logic*.
- **No rubric content, no built-in rubrics, no validation of question wording.**
  LabJury does not know what a "good" rubric is.
- **No deletion / mutation of a published version.** Versions are immutable once
  registered — that is what makes them a reproducibility handle. `register` only
  adds; there is no `delete`/`update` surface (same immutability stance as
  `AuditLog`).

## Constraints (inherited)

- Core `dependencies = []`; stdlib-only; mechanism lives in `labjury.rubrics`
  (core namespace, like `reliability`/`redaction`/`guards`/`secrets`); core never
  imports `labjury.contrib`.
- **Public plugin contract stays backward-compatible.** The only contract touch is
  an *optional, defaulted* field on `Candidate` — additive, like `latency_ms` on
  `ItemResult` at step 3. No existing signature changes.
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.
- Conformance suite ships in the installed package (`labjury.testing`), not under
  `tests/`, so third parties can import it.

## The parts of the how, as decided

### `Rubric` + `RubricStore` (`labjury/rubrics.py` + `labjury/plugins.py`)

```python
# labjury/rubrics.py
@dataclass(frozen=True)
class Rubric:
    label: str
    question: Question
    version: str

# labjury/plugins.py
@runtime_checkable
class RubricStore(Protocol):
    async def register(self, label: str, question: Question, version: str) -> Rubric: ...
    async def resolve(self, label: str) -> Rubric | None: ...
    async def get(self, label: str, version: str) -> Rubric | None: ...
    async def history(self, label: str) -> list[str]: ...
```

`InMemoryRubricStore` keeps, per label, an ordered mapping `version -> Rubric`;
`resolve` returns the last inserted; `get` indexes by version; `history` lists the
keys in order. Re-registering an existing `(label, version)` with an equal
question returns the stored rubric unchanged; with a different question it raises
`ValueError` ("version already published with a different question").

**Why `register` returns the `Rubric`:** the caller (a proposer) immediately needs
both the question and the version to build its `Candidate`; returning the stored
object saves a `resolve` round-trip and pins exactly what was stored.

### The reproducibility link (`labjury/decisions.py` + `labjury/audit.py`)

`Candidate` gains `rubric_version: str | None = None` (last field, defaulted).
`candidate_to_dict` adds `"rubric_version": c.rubric_version`;
`candidate_from_dict` reads `d.get("rubric_version")`. A proposer that sources its
question from the registry sets it:

```python
r = await store.resolve(label)
Candidate(label, kind, r.question, rubric_version=r.version)
```

Replay (`replay_decision`) already round-trips candidates through
`candidate_from_dict`; the version survives for free and no replay logic changes.

### Public surface

Re-exported from `labjury` under a `# rubric registry` group: `Rubric`,
`RubricStore`, `InMemoryRubricStore`, `assert_rubric_store_contract`. Added to
`test_public_api.py`'s importable list.

## What's left to the builder

- Internal data structure of `InMemoryRubricStore` (a `dict[str, dict[str, Rubric]]`
  with insertion-ordered inner dicts is the obvious choice; the tests pin behavior,
  not representation).
- Exact wording of the `ValueError` message.
- Test fixture labels/questions/version strings.

## Review focus (inputs the tests must pin)

- **Re-publishing a version with a different question raises** `ValueError`
  (immutability of a published version — the whole point of versioning).
- **`resolve` returns the latest** registered version, not the first, after
  several registrations for one label.
- **`get(label, old_version)` still returns the old rubric** after a newer version
  is registered (the reproducibility read survives supersession).
- **A `Candidate` built without `rubric_version` round-trips** through
  `candidate_to_dict`/`from_dict` with `rubric_version is None` — proving the audit
  path is backward-compatible with pre-registry candidates.
- **`resolve`/`get`/`history` on an unregistered label** return `None`/`None`/`[]`
  (no `KeyError`).
