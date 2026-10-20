# Human-in-the-loop review — a stateless, fire-and-forget hand-off contract

**Status:** design (CTO-decided; owner delegated design authority, "ok" 2026-10-20) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness **Tier 2** (operability at scale), **item 4 of 5** — human-in-the-loop review queue. Builds on the audit trail (the review package is the audit package) and tenant attribution.

## Intent and the why

The engine already decides `Status.REVIEW` when a policy returns `Action.REVIEW`:
the machine is not confident enough, a human should adjudicate. Today such a result
just reaches the sink; there is no contract for handing it to a human and bringing
the human's decision back.

LabJury must provide that contract **without owning the queue**. The hand-off was
settled earlier as **stateless and fire-and-forget**: the framework packages a
review task, hands it off, and forgets it — it does not hold state waiting for a
human, run a consumer loop, or manage the message broker. Every company already has
its own review infrastructure (a ticketing system, a labeling tool, an SQS queue, a
DB table); LabJury stays autonomous of all of it. This is the same "bring your own
storage / own the seam, not the backend" rule as every other tier, applied to
orchestration.

So this slice ships the **contract and the seam**:

- a portable `ReviewTask` (what a human needs to adjudicate) and a builder that
  turns a recorded decision into one;
- a portable `ReviewResolution` (the human's decision) and its conversion to a final
  `Verdict`;
- a `ReviewQueue` protocol (fire-and-forget `enqueue`) and a zero-dep in-memory
  reference.

The engine is **not** changed: wiring REVIEW results to a queue, and feeding human
decisions back, is deployer orchestration — exactly what the fire-and-forget
contract keeps out of the framework.

## Goals

- **`ReviewTask`** (`labjury.review.ReviewTask`, frozen, serializable) — the
  adjudication package: `correlation_id`, `candidates: tuple[dict, ...]`,
  `answers: tuple[dict, ...]`, `tentative_verdict: dict | None` (what the machine
  tentatively decided), `tenant: str | None = None`, `created_at: str`
  (ISO, default now). `to_dict()` / `from_dict()`.
- **`review_task_from_event(event: AuditEvent) -> ReviewTask`** — builds a task from a
  recorded decision; the `AuditEvent` already carries the candidates, answers,
  verdict, tenant, and correlation id, so the review package *is* the audit package.
- **`ReviewResolution`** (`labjury.review.ReviewResolution`, frozen, serializable) —
  the human's decision: `correlation_id`, `action: str` (an `Action` value —
  `"accept"`/`"block"`/`"review"`), `labels: list[str]`, `reviewer: str`,
  `note: str = ""`, `decided_at: str` (ISO, default now). `to_dict()` / `from_dict()`.
  - `to_verdict() -> Verdict` — the human decision as a final verdict:
    `Verdict(Action(action), labels, {}, [], note or f"human review by {reviewer}")`.
    Scores are empty (a human produced no model scores).
- **`ReviewQueue`** (`labjury.plugins.ReviewQueue`, `@runtime_checkable`):
  - `async def enqueue(self, task: ReviewTask) -> None` — fire-and-forget: hand the
    task to the backend and return. LabJury never pulls, acks, or waits.
- **`InMemoryReviewQueue`** (`labjury.review`) — zero-dep reference: `enqueue` appends;
  `pending() -> list[ReviewTask]` returns the enqueued tasks (inspection);
  `drain() -> list[ReviewTask]` returns and clears them (simulating a consumer pull).
- **Public surface:** re-export `ReviewTask`, `ReviewResolution`, `ReviewQueue`,
  `InMemoryReviewQueue`, `review_task_from_event` from `labjury`; add to
  `test_public_api.py`.
- **Docs:** `docs/human-review.md` + bilingual README pointers.

## Non-goals / anti-goals

- **No engine change / no auto-enqueue.** The engine does not hold a `ReviewQueue` and
  does not enqueue on `Status.REVIEW`. The deployer wires that (see a REVIEW result →
  read its audit event → `review_task_from_event` → `queue.enqueue`), keeping the
  framework autonomous of orchestration. Documented, not built.
- **No consumer loop, no ack/nack, no visibility timeout, no assignment, no SLA or
  escalation.** Those are the deployer's review-workflow concerns. LabJury's side of
  the contract is one write (`enqueue`) and the two portable value objects.
- **No conformance suite for `ReviewQueue`.** It is a single fire-and-forget method
  with no multi-step stateful invariant to assert; the `@runtime_checkable` protocol
  is the structural check — the same ruling as the `Observer` protocol (telemetry
  step), and unlike the multi-method stateful `TaxonomyStore`/`RubricStore`/`AuditLog`.
- **No queue storage.** `InMemoryReviewQueue` is a reference, not a production broker;
  durable backends (SQS, DB, Pub/Sub) are bring-your-own, trivially implementing one
  `enqueue`.
- **No recording of the human override in this slice.** Applying a resolution to the
  audit trail (so "machine REVIEW → human decided X" is auditable) is a documented
  extension the deployer composes from existing pieces (`to_verdict` + an `AuditEvent`
  with a reviewer provenance); folding it in would couple review → audit writes.

## Constraints (inherited)

- Core `dependencies = []`; stdlib only; mechanism in `labjury.review` (core) + the
  protocol in `labjury.plugins`. Core never imports `labjury.contrib`.
- No public plugin contract change; all additions are new types / a new protocol.
- Value objects are JSON-serializable through `to_dict`/`from_dict` (they cross to an
  external system). `from_dict` tolerates missing optional keys.
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### Value objects (`labjury/review.py`)

```python
@dataclass(frozen=True)
class ReviewTask:
    correlation_id: str
    candidates: tuple[dict, ...] = ()
    answers: tuple[dict, ...] = ()
    tentative_verdict: dict | None = None
    tenant: str | None = None
    created_at: str = field(default_factory=_now_iso)

@dataclass(frozen=True)
class ReviewResolution:
    correlation_id: str
    action: str
    labels: list[str]
    reviewer: str
    note: str = ""
    decided_at: str = field(default_factory=_now_iso)
    def to_verdict(self) -> Verdict: ...

def review_task_from_event(event: AuditEvent) -> ReviewTask: ...
```

`review_task_from_event` copies `event.correlation_id`, `event.candidates`,
`event.answers`, `event.verdict` (as `tentative_verdict`), and `event.tenant`.
`_now_iso` mirrors the one in `audit.py` (UTC ISO).

### `ReviewQueue` + `InMemoryReviewQueue`

`ReviewQueue` is one async `enqueue`. `InMemoryReviewQueue` holds a list; `enqueue`
appends, `pending` returns a copy, `drain` returns a copy and clears.

### Public surface

Re-exported from `labjury` under a `# human review` group: `ReviewTask`,
`ReviewResolution`, `ReviewQueue`, `InMemoryReviewQueue`, `review_task_from_event`.
Added to `test_public_api.py`.

## What's left to the builder

- `to_dict`/`from_dict` exact key spelling (follow the field names).
- `InMemoryReviewQueue` internal representation (a list; `pending`/`drain` return
  copies so callers can't mutate internals).
- Test fixtures.

## Review focus (inputs the tests must pin)

- **`review_task_from_event` carries candidates/answers/verdict/tenant/correlation**
  from a realistic `AuditEvent` — pinned in Task 1.
- **`ReviewTask` and `ReviewResolution` round-trip** through `to_dict`/`from_dict`,
  and `from_dict` tolerates a dict missing the optional keys — pinned in Task 1.
- **`ReviewResolution.to_verdict()` maps `action` to the `Action` enum**, keeps
  labels, empties scores, and sets a reason — pinned in Task 1; an **unknown action
  string raises** (`Action(bad)` → `ValueError`) — pinned in Task 1.
- **`InMemoryReviewQueue.enqueue` is fire-and-forget** (returns `None`); `pending`
  reflects enqueued order; `drain` empties — pinned in Task 2.
- **`drain`/`pending` return copies** — mutating the returned list does not change the
  queue — pinned in Task 2.
