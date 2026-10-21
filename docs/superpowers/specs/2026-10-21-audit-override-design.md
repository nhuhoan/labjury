# Audit the human override — close the review loop

**Status:** design (CTO-decided; owner delegated the post-roadmap "small extensions", one at a time)
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap extension #2. Named in the review-queue note as the
documented extension ("deployer composes an `AuditEvent` from task+resolution with
reviewer provenance").

## Intent and the why

The audit trail records every *machine* decision. When a decision is
`Status.REVIEW`, `review_task_from_event` packages it and hands it to the
deployer's queue — a **one-way exit** from the audit trail. The human's final
decision (`ReviewResolution`) converts back to a `Verdict` via `to_verdict()`,
but nothing records *that a human overrode the machine, who, and when* as an
immutable event. For a governance/audit system that is the one gap that matters:
an override with no audit record is exactly the decision a regulator asks about.

This slice ships the inverse of `review_task_from_event`: a pure function that
turns the original decision event plus the human's resolution into a **new**
`AuditEvent` recording the override, linked to the original by `correlation_id`.

## Goals

- **`labjury.review.override_event(event: AuditEvent, resolution: ReviewResolution) -> AuditEvent`** —
  a new immutable event that:
  - **links** to the original: same `correlation_id`; raises `ValueError` if
    `resolution.correlation_id != event.correlation_id` (recording an override
    against the wrong decision is an error worth catching);
  - **carries forward the inputs the human saw**: `input_fingerprint`,
    `modalities`, `candidates`, `answers`, `known_labels`, `tenant` from the
    original event;
  - **records the human's verdict**: `verdict = verdict_to_dict(resolution.to_verdict())`
    (action + labels, empty scores — a human produced no model scores);
  - **attributes it to the human**: `provenance = {"reviewer": ProvenanceRef(
    name=resolution.reviewer, version=None, params={"note": ..., "decided_at": ...})}`
    — and *only* the reviewer, not the machine's scorer/policy provenance: this
    event asserts "the human decided this"; the original event (same
    `correlation_id`) still holds the machine provenance, and the two together
    tell the full story;
  - is a **distinct event**: fresh `event_id` and `occurred_at` (it is not the
    machine decision; it is a later, separate record).

## Non-goals / anti-goals

- **No engine change, no new type, no contract change** — a pure read producing an
  existing `AuditEvent`; the deployer appends it to their `AuditLog` themselves.
- **No judgment of the override** — LabJury does not check whether the human
  "should" have overridden, nor that the original was actually `REVIEW`; it
  records what happened. (The `correlation_id` guard is a wiring check, not a
  policy judgment.)
- **Machine provenance is deliberately NOT merged in** — see above; conflating
  would misrepresent who made *this* verdict.
- **No auto-enqueue / consumer loop** — orchestration stays with the deployer, as
  the review-queue contract already established.

## Constraints (inherited)

- Pure core, zero-dep; lives in `labjury.review` (the bridge between review types
  and `AuditEvent`, which already owns `review_task_from_event` and imports
  `AuditEvent`).
- The produced event round-trips through `AuditEvent.to_dict`/`from_dict` like any
  other (provenance params carry a JSON-safe dict).
- Python 3.11+. TDD; commit per task.

## Review focus (inputs the tests must pin)

- `correlation_id` preserved; mismatch → `ValueError`.
- `verdict` equals the resolution's `to_verdict()` serialized (action, labels,
  empty scores).
- `provenance["reviewer"]` carries the reviewer name and the note/decided_at in
  params; machine provenance is absent.
- Inputs (`input_fingerprint`, `candidates`, `answers`, `tenant`, `known_labels`)
  carried forward from the original.
- Fresh `event_id` (distinct from the original); result round-trips through
  `to_dict`/`from_dict`.
