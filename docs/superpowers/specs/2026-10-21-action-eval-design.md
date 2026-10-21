# Action-level evaluation — the operational decision, scored

**Status:** design (CTO-decided; owner delegated the post-roadmap "small extensions", one at a time)
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap extension #3. Named in the evaluation-harness note as
the documented extension ("action-level confusion on `run_evaluation` per-case").

## Intent and the why

The evaluation harness scores the verdict **labels** (multi-label precision/recall/
F1). But the decision that actually *ships* is the **action** — `ACCEPT` / `BLOCK`
/ `REVIEW`. For a moderation pipeline "did we block the right things, and not
over-block?" is often THE question, and it is a 3-class classification, not a
multi-label set. A pipeline can have good label F1 yet route the wrong action
(e.g. labels right but the policy sends too much to `REVIEW`). This slice adds
action-level scoring alongside the existing label scoring, reusing the same
`LabelScore` math for per-action one-vs-rest metrics.

## Goals

- **`labjury.evaluation.ActionReport`** — a frozen report over expected-vs-predicted
  actions: `n_cases: int`, `confusion: dict[tuple[str, str], int]` (keyed by
  `(expected_action_value, predicted_action_value)`), `per_action: dict[str, LabelScore]`
  (one-vs-rest per real action), and an `accuracy` property (diagonal sum / n_cases).
- **`labjury.evaluation.score_actions(pairs: Iterable[tuple[Action, Action | None]]) -> ActionReport`** —
  the pure core. `predicted is None` means the pipeline produced no action (a
  `FAILED` item); it is bucketed under the predicted key `"none"`, counts as a
  false negative for the expected action, and is never a true positive. `expected`
  is always a real `Action`. `per_action` is computed one-vs-rest over the real
  action classes seen in `expected` (a `LabelScore` with `label=action.value`):
  `tp = confusion[(a,a)]`, `fp = predicted a but expected ≠ a`, `fn = expected a
  but predicted ≠ a`.
- **Additive optional `GoldenCase.expected_action: Action | None = None`** — the
  ground-truth action for a case. Defaulted so existing label-only golden sets
  and positional `GoldenCase(item, labels)` construction are unchanged.
- **`labjury.evaluation.run_action_evaluation(engine, cases) -> ActionReport`** —
  runs a golden set through the engine and scores `result.verdict.action` (None
  when there is no verdict) against `case.expected_action`. Raises `ValueError` if
  any case has `expected_action is None` (you cannot action-score a case with no
  ground-truth action).

## Non-goals / anti-goals

- **No change to the label path** — `score_predictions` / `run_evaluation` /
  `EvalReport` are untouched; action scoring is a parallel, additive capability.
- **No action-level regression diff in this slice** — `compare_evals` stays
  label-focused (`ActionReport` exposes `accuracy` and `per_action` F1 for a
  deployer to gate on directly; a dedicated comparator is a later extension if
  asked).
- **No engine/contract change** — `GoldenCase` gains one defaulted field; the
  runner uses only the public `engine.process`.
- **No judgment of which action is "worse" to miss** — the confusion matrix is
  reported raw; cost-weighting (e.g. a missed `BLOCK` costs more than a spurious
  `REVIEW`) is the deployer's policy over these counts.

## Constraints (inherited)

- Pure core, zero-dep; lives in `labjury.evaluation`; reuses `LabelScore`/`_ratio`.
- Deterministic; raw ratios (no rounding), `0.0` on zero denominators.
- Python 3.11+. TDD; commit per task.

## Review focus (inputs the tests must pin)

- All-correct predictions → `accuracy == 1.0`, each `per_action.f1 == 1.0`.
- A misroute (expected `BLOCK`, predicted `REVIEW`) → off-diagonal confusion
  entry; the expected action's recall and the predicted action's precision both
  drop.
- `predicted is None` (FAILED) → `"none"` predicted bucket, counts as fn for the
  expected action, never a tp.
- `run_action_evaluation` maps a no-verdict result to `None`; raises `ValueError`
  when a case has no `expected_action`.
- Empty pairs / no cases → `accuracy == 0.0`, empty `per_action`.
