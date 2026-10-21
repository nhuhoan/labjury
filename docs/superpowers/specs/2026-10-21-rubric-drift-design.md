# Rubric-vs-registry drift — a reproducibility check

**Status:** design (CTO-decided; owner delegated the post-roadmap "small extensions", one at a time)
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap extension #1 of the remaining queue. Named in the
reproducibility note as "the natural extension" (`RubricStore.get(label, version)`
+ compare question).

## Intent and the why

Reproducibility (Tier 2 item 2) gave `verify_replay`: re-run the *policy* over a
recorded event and detect *policy* version drift. A decision also depends on the
**rubric** — the `Question` asked about each label — which a proposer optionally
sources from a `RubricStore` and records as `Candidate.rubric_version`.

A published `(label, version)` rubric is immutable *by contract*, so in a healthy
system the question recorded on a candidate must still equal the one the registry
holds for that version. When it doesn't, something is wrong: the registry was
rebuilt/tampered, the decision used an ad-hoc question that was labelled with a
registry version it didn't come from, or two stores diverged. This slice ships
the mechanism that **detects** that — it does not judge the rubric content.

## Goals

- **`labjury.audit.RubricDrift`** — frozen record of one inconsistency:
  `label: str`, `version: str`, `reason: str`, `recorded_question: dict`,
  `registry_question: dict | None` (None when the version is absent from the
  registry).
- **`async labjury.audit.rubric_drift(event, store) -> list[RubricDrift]`** —
  for each recorded candidate carrying a `rubric_version`, fetch
  `await store.get(label, version)` and compare the recorded question dict to the
  registry's `question_to_dict(stored.question)`:
  - version absent from registry → one drift, `reason="version absent from registry"`,
    `registry_question=None`;
  - present but question differs → one drift, `reason="question differs from registry"`;
  - equal → no drift.
  Candidates with `rubric_version is None` are skipped (not sourced from a
  registry). Returns `[]` when every registry-sourced candidate is consistent
  (the faithful case).

## Non-goals / anti-goals

- **No judgment of rubric content** — equality of the serialized question only;
  LabJury never rates whether a question is "good".
- **No engine change, no contract change** — a pure read over an existing
  `AuditEvent` and any `RubricStore`.
- **No mutation / repair** — detection only; what to do about drift (alert,
  quarantine, re-decide) is the deployer's.
- **Not folded into `verify_replay`** — that one is sync and takes a *policy*;
  this one is async and takes a *store*. Different inputs, different stage.
- **Cache-hit events** are fine: they carry no candidates, so the result is `[]`.

## Constraints (inherited)

- Pure core, zero-dep; lives in `labjury.audit` (it composes `question_to_dict`,
  already the question-serialization home).
- `store` is duck-typed to an `async get(label, version) -> Rubric | None` — audit
  does not import `labjury.plugins`/`rubrics`; any conforming store works.
- Python 3.11+. TDD; commit per task.

## Review focus (inputs the tests must pin)

- A candidate whose `rubric_version` is **absent** from the registry → one drift
  with `registry_question=None`.
- A candidate whose recorded question **differs** from the registry's → one drift.
- A candidate with `rubric_version=None` → **skipped** (no drift, no `get` call).
- An all-consistent event → `[]`; a cache-hit / no-candidate event → `[]`.
