# Immutable, replayable audit trail — design

Date: 2026-10-20
Status: proposed (Tier 1, step 2a of the enterprise-readiness roadmap —
storage-agnostic audit contract; a durable reference backend is the separate
follow-on 2b)
Author's note: the decisions below are **my (CTO) calls** under the owner's
"you decide" delegation, not choices the owner signed off on individually.
The owner's checkpoint is the implementation plan that follows this doc.

## Intent & why

A large company will not place content-moderation decisions on a system it
cannot interrogate afterwards. When a decision is appealed ("why was my
content blocked?"), audited by compliance, or debugged by an engineer, the
organization must be able to pull up *that exact decision* and see — and
reproduce — how it was reached. This is the single feature that turns "a nice
library" into "a system a compliance department trusts." It is why the roadmap
names audit + reproducibility the highest-leverage step.

This builds directly on step 1: the durable taxonomy gives decisions a stable
vocabulary; the audit trail records what was decided against it.

## Goals

- Record one **immutable** `AuditEvent` for every decision the engine makes,
  capturing enough to both *explain* and *reproduce* it: input fingerprint,
  modalities, route taken, the candidates and the scorer's answers, the
  provenance of the plugins involved (name + version + params), the taxonomy's
  official vocabulary at decision time, and the resulting verdict.
- **Deterministic replay:** given a recorded event and a policy, re-run the
  decision policy over the recorded inputs and reproduce the verdict — so an
  auditor can see *why*, and an engineer can test what a policy change would
  have done to history.
- An `AuditLog` **protocol** (append-only) with an in-memory default, plus a
  reusable **conformance suite** so a company can back audit with their own
  system (Kafka, S3, a SIEM, Postgres, SQLite) and prove it conforms. This
  step ships **no database backend** — the contract, not any one store, is the
  deliverable, because every company has its own storage.
- `AuditEvent` is **JSON-serializable** with `to_dict()` / `from_dict()`. This
  is the extensibility seam: any backend persists and reloads events through
  plain dicts without touching LabJury internals, so "bring your own storage"
  is real, not theoretical.
- Core stays **zero-dependency**; audit is opt-in and defaults to a no-op.
- No breaking change to any existing plugin contract.

## Non-goals / anti-goals

- **Not** recording raw item content. The event stores a content *fingerprint*
  (sha256, reusing the engine's cache-key hash) and the modality set — never
  the payload. Storing user content by default is a compliance anti-goal; a
  deployer who needs it extends their own backend.
- **Not** replaying the scorer/LLM. Model calls are non-deterministic; their
  outputs are *recorded* (the answers) and replayed from the record, not
  re-executed. Faithful replay covers the **decision policy** over recorded
  (candidates, answers, taxonomy snapshot). A policy that reads raw `state`
  content beyond candidates/answers is outside faithful-replay scope (the
  default `RecallBiasedPolicy` is fully in scope).
- **Not** mutable. The protocol exposes `record` + reads only — no update, no
  delete. Append-only is the point.
- **Not** auditing failures or taxonomy promote-attribution ("who promoted a
  label") this step. Both are real and tracked as follow-ons; folding them in
  now would blur a clean first slice. This step audits **decided and
  cache-served** verdicts.

## Decisions (the "how")

1. **`AuditEvent` (immutable, in `labjury.audit`)** — a frozen dataclass:
   `event_id` (uuid4 hex), `occurred_at` (UTC ISO-8601 string), `correlation_id`
   (the item id), `input_fingerprint` (str), `modalities` (frozenset[str]),
   `from_cache` (bool), `used_proposer` (bool | None), `candidates`
   (tuple of recorded candidate dicts: label, kind, question-as-dict), `answers`
   (tuple of recorded answer dicts: key, value, confidence, distribution),
   `known_labels` (frozenset[str], the taxonomy snapshot at decision time),
   `provenance` (dict of role → `ProvenanceRef`, roles `scorer` and `policy` —
   the two that determine/transform the verdict; proposer identity is out of
   this slice since the candidates are recorded), and `verdict` (a plain dict
   mirror of `Verdict`: action value, labels, scores, novel_labels, reason).
   Fields that do not apply to a thin cache-hit event default to empty. The
   event exposes `to_dict() -> dict` (all values JSON-native: frozensets become
   sorted lists) and a classmethod `from_dict(d) -> AuditEvent`, round-trip
   exact. This pair is the single serialization seam every backend uses, so a
   backend never needs to understand LabJury's internal types.

2. **`ProvenanceRef`** — frozen dataclass `(name: str, version: str | None,
   params: dict | None)`. Captured from a plugin as
   `ProvenanceRef(type(p).__name__, getattr(p, "version", None),
   getattr(p, "params", None))`. `version`/`params` are an **optional,
   non-breaking convention**: plugins that expose them get richer provenance,
   plugins that don't still record their class name. `RecallBiasedPolicy` gains
   a small `params` property returning its thresholds, so thresholds are
   captured.

3. **`AuditLog` protocol (new plugin kind, in `labjury.plugins`)** — append-only:
   `async def record(self, event: AuditEvent) -> None` and
   `async def by_correlation(self, correlation_id: str) -> list[AuditEvent]`
   (events in record order). No update/delete method exists. Add `audit_logs`
   to the registry's plugin kinds and to the declared entry-point groups, for
   contract completeness (third-party *zero-arg* audit logs can register); like
   step 1, DI-style backends needing an injected connection are used by direct
   import, not entry-points.

4. **Defaults (`labjury.defaults`)** — `NullAuditLog` (records nothing; the
   safe zero-cost default so core stays lean and existing behavior is
   unchanged) and `InMemoryAuditLog` (keeps a list; for dev/test and the
   conformance suite). `InMemoryAuditLog` passes the conformance suite;
   `NullAuditLog` is the deliberate opt-out — it satisfies the protocol surface
   but, since it retains nothing, is exempt from the retrieval conformance
   (recording nothing is its contract).

5. **Engine integration** — new keyword-only constructor param
   `audit: AuditLog | None = None`, defaulting to `NullAuditLog()` built in
   `__init__` (no mutable default). In `_run`: on a cache hit, record a thin
   event (`from_cache=True`, fingerprint, verdict); on a full decision, record
   a complete event after the verdict is computed. The fingerprint reuses
   `self._cache_key(item)` so audit and cache agree on identity. Auditing is a
   side record; a failure in `record` must not change the verdict returned to
   the caller (wrap defensively, surface via the observer).

6. **Replay (`labjury.audit`)** —
   `async def replay_decision(event: AuditEvent, policy: DecisionPolicy)
   -> Verdict`: rebuild a frozen read-only taxonomy from `event.known_labels`,
   reconstruct `Candidate`/`Answer` objects from the recorded dicts, call
   `policy.decide(State(), candidates, answers, frozen_taxonomy)`, and return
   the `Verdict`. Plus `def verdict_matches(event: AuditEvent, verdict: Verdict)
   -> bool` comparing a replayed verdict to the recorded one. Replaying a
   `from_cache` event raises `ValueError` (nothing to replay — the original
   decision's event is the replayable one).

7. **No database backend this step (decided).** The whole point — per the
   owner's constraint that every company has its own storage — is that LabJury
   ships the *contract*, not a store. A durable reference backend is the
   separate follow-on **2b** (see below); the `to_dict`/`from_dict` seam plus
   the conformance suite are what make any such backend a drop-in, ours or
   theirs.

## Testing strategy ("làm chắc")

- **Conformance suite** `assert_audit_log_contract(make_log)` in
  `labjury.testing`: record several events (including two for the same
  `correlation_id`), assert `by_correlation` returns them in order and is empty
  for an unknown id, and assert the type is append-only (no `update`/`delete`
  attribute in the protocol surface). `InMemoryAuditLog` runs it; a third-party
  backend (and the 2b reference backend) run the same suite.
- **Serialization round-trip:** `from_dict(to_dict(event)) == event` for both a
  full decided event and a thin cache-hit event, and `to_dict(event)` survives
  `json.dumps`/`json.loads` unchanged — this is the seam every backend relies
  on, so it is pinned directly.
- **Replay tests:** a decided event replayed through `RecallBiasedPolicy`
  reproduces its verdict; a known-label snapshot drives novel-label detection
  identically; a `from_cache` event raises on replay.
- **Engine tests:** a decided item produces one full event with populated
  provenance (scorer and policy names, policy params, known-labels
  snapshot); a cache hit produces a thin `from_cache` event; the audit log
  never receives raw item content (fingerprint only); a `record` that raises
  does not break `process`.
- Full suite stays green with **zero third-party packages** (this step adds no
  dependency and no extra).

## Follow-on: step 2b — a durable reference backend

Out of scope here, planned next: one durable `AuditLog` reference backend so
the trail survives restarts out of the box, shipped under `labjury.contrib.*`
behind its own optional extra, verified by this step's conformance suite. The
store choice (SQLite for dependency-free, real-DB testing vs Postgres for
scale) is deferred to that step — deliberately, so no database is baked in
before the contract has proven itself and so companies see it as one optional
reference among many, not "the" backend.

## Left to the builder

- Where `replay_decision` builds its frozen taxonomy (a tiny local read-only
  class vs reusing `InMemoryTaxonomyStore` pre-seeded).
- Serialization details of questions/answers to plain dicts and back.
- Whether `AuditEvent`/`replay_decision`/`assert_audit_log_contract` are
  re-exported at top level (default: yes for `AuditEvent` and
  `replay_decision`; the conformance helper lives in `labjury.testing`).
