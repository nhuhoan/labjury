# Evaluation harness — golden sets, precision/recall, policy regression

**Status:** design (CTO-decided; owner delegated design authority, "ok" 2026-10-20) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness **Tier 2** (operability at scale), **item 5 of 5 — closes Tier 2**. Builds on the engine's public `process` API and the `Verdict.labels` output.

## Intent and the why

For an enterprise the question is not only "does it run" but "is it *accurate*, and
did my last change make it better or worse?" A moderation/labeling pipeline that
silently regresses is worse than useless — it ships wrong decisions at scale. So the
tier closes with the mechanism to measure accuracy against ground truth and to catch
regressions before they ship:

- **Golden sets** — ground-truth examples (an item and the labels a correct pipeline
  should produce).
- **Precision / recall / F1** — the standard label-set metrics, per label and
  aggregated.
- **Policy regression** — run the harness before and after a change, compare, and
  flag any drop.

Same seam philosophy as the whole roadmap: LabJury owns the **measurement
mechanism**, not the data and not the test runner. It does not ship golden datasets
(those are the deployer's labeled data, in their domain, under their policy), and it
does not integrate with any CI system (the deployer calls these functions from their
own test suite / pipeline). The math is pure, deterministic, and zero-dependency.

## Goals

- **Pure metric core (`labjury.evaluation`):**
  - `LabelScore` (frozen): `label: str`, `tp: int`, `fp: int`, `fn: int`; properties
    `precision`, `recall`, `f1` (each `0.0` when its denominator is zero).
  - `EvalReport` (frozen): `n_cases: int`, `exact_matches: int`,
    `per_label: dict[str, LabelScore]`; properties `micro_precision`,
    `micro_recall`, `micro_f1` (over summed tp/fp/fn across labels),
    `macro_precision`, `macro_recall`, `macro_f1` (mean of the per-label values,
    `0.0` when there are no labels), and `exact_match_rate`
    (`exact_matches / n_cases`, `0.0` when `n_cases == 0`).
  - `score_predictions(pairs: Iterable[tuple[set[str], set[str]]]) -> EvalReport` —
    each pair is `(expected_labels, predicted_labels)`. Accumulates per-label
    `tp`/`fp`/`fn` over the union of labels seen, counts an exact match when
    `expected == predicted`, and `n_cases`.
- **Golden set + runner:**
  - `GoldenCase` (frozen): `item: Item`, `expected_labels: frozenset[str]`.
  - `run_evaluation(engine, cases: Iterable[GoldenCase]) -> EvalReport` (async) —
    runs `engine.process(case.item)` for each case, takes the predicted labels from
    `result.verdict.labels` (or the empty set when there is no verdict, e.g. a
    `FAILED` result — a pipeline that fails to decide earns no credit), and delegates
    to `score_predictions`.
- **Policy regression:**
  - `EvalComparison` (frozen): `baseline: EvalReport`, `candidate: EvalReport`,
    `micro_f1_delta: float`, `macro_f1_delta: float`, `regressed_labels: list[str]`
    (labels whose per-label F1 is lower in the candidate than the baseline); method
    `regressed(tolerance: float = 0.0) -> bool` (`micro_f1_delta < -tolerance`).
  - `compare_evals(baseline: EvalReport, candidate: EvalReport) -> EvalComparison`.
- **Public surface:** re-export `LabelScore`, `EvalReport`, `score_predictions`,
  `GoldenCase`, `run_evaluation`, `EvalComparison`, `compare_evals` from `labjury`;
  add to `test_public_api.py`.
- **Docs:** `docs/evaluation.md` + bilingual README pointers.

## Non-goals / anti-goals

- **No built-in golden datasets or fixtures.** The golden set is the deployer's
  labeled data, loaded and stored however they like ("bring your own storage/data").
- **No CI/test-runner integration.** `compare_evals` and `EvalComparison.regressed`
  return values; the deployer asserts on them in their own pipeline. LabJury does not
  own the gate.
- **No scorer-only or proposer-only evaluation.** The harness measures the
  end-to-end pipeline's verdict labels — the decision that actually ships. Component
  micro-benchmarks are the deployer's.
- **No ranking/threshold sweeps, calibration, or confidence-interval statistics.**
  Point metrics (P/R/F1, exact-match) over a labeled set; distributional analysis is
  out of scope.
- **No action/verdict-shape evaluation in this slice.** Metrics are over the label
  set (`verdict.labels`), the core of a labeling framework. Action-level
  (accept/block/review) confusion is a documented extension.
- **No new dependency, no storage.** Pure stdlib math, in core.

## Constraints (inherited)

- Core `dependencies = []`; stdlib only; mechanism in `labjury.evaluation` (core).
  Core never imports `labjury.contrib`.
- No public plugin contract change; all additions are new functions / value objects.
  `run_evaluation` consumes only the public `Engine.process` / `ItemResult` surface.
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### Metric core + regression (`labjury/evaluation.py`)

```python
@dataclass(frozen=True)
class LabelScore:
    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    @property
    def precision(self) -> float: ...   # tp/(tp+fp) or 0.0
    @property
    def recall(self) -> float: ...      # tp/(tp+fn) or 0.0
    @property
    def f1(self) -> float: ...          # 2pr/(p+r) or 0.0

@dataclass(frozen=True)
class EvalReport:
    n_cases: int
    exact_matches: int
    per_label: dict[str, LabelScore]
    # micro_* / macro_* / exact_match_rate as properties

def score_predictions(pairs) -> EvalReport: ...

@dataclass(frozen=True)
class EvalComparison:
    baseline: EvalReport
    candidate: EvalReport
    micro_f1_delta: float
    macro_f1_delta: float
    regressed_labels: list[str]
    def regressed(self, tolerance: float = 0.0) -> bool: ...

def compare_evals(baseline, candidate) -> EvalComparison: ...
```

`score_predictions` builds the per-label counts by walking each pair: for the union
of expected and predicted, `tp` where in both, `fp` where predicted only, `fn` where
expected only. Micro sums those; macro means the per-label properties.

### Golden set + runner (`labjury/evaluation.py`)

```python
@dataclass(frozen=True)
class GoldenCase:
    item: Item
    expected_labels: frozenset[str]

async def run_evaluation(engine, cases) -> EvalReport: ...
```

`run_evaluation` is deliberately thin — it calls the public `process`, reads
`result.verdict.labels if result.verdict else []`, and reuses `score_predictions`.

### Public surface

Re-exported from `labjury` under an `# evaluation` group: `LabelScore`,
`EvalReport`, `score_predictions`, `GoldenCase`, `run_evaluation`, `EvalComparison`,
`compare_evals`. Added to `test_public_api.py`.

## What's left to the builder

- Internal accumulation structure in `score_predictions` (a dict of mutable counters
  folded into frozen `LabelScore`s at the end is the obvious shape).
- Float formatting / rounding is **not** applied — raw ratios are returned; any
  display rounding is the caller's.
- Test fixtures (a fake engine returning a chosen `Verdict` per item is enough for
  `run_evaluation`; the module's existing engine fakes may be reused).

## Review focus (inputs the tests must pin)

- **A worked multi-label example** yields the exact micro P/R, a per-label F1, and the
  exact-match rate (pinned numbers) — Task 1.
- **Division-by-zero is `0.0`, never an error**: a label with `tp+fp == 0` precision
  `0.0`; an empty report (`n_cases == 0`) all-`0.0` metrics and `exact_match_rate 0.0`
  — Task 1.
- **`compare_evals` flags a micro-F1 drop** (`regressed()` true) and lists the
  regressed label; an improvement is not a regression; `tolerance` absorbs a small
  drop — Task 1.
- **`run_evaluation` treats a no-verdict / `FAILED` result as an empty prediction**
  (expected labels become `fn`, no credit) — Task 2.
- **`run_evaluation` over a fake engine** reproduces the same report
  `score_predictions` would give for those predictions — Task 2.
