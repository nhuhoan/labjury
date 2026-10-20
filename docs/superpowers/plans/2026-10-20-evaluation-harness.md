# Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a zero-dep evaluation harness — pure label-set precision/recall/F1 metrics (`score_predictions` → `EvalReport`), a golden-set runner over the engine (`GoldenCase`, `run_evaluation`), and a policy-regression comparison (`compare_evals` → `EvalComparison`) — closing Tier 2.

**Architecture:** `labjury.evaluation` holds everything. The metric core is pure and deterministic: `score_predictions` turns `(expected, predicted)` label-set pairs into an `EvalReport` of per-label `tp/fp/fn` with micro/macro P/R/F1 and exact-match rate as properties. `run_evaluation` is a thin async runner that calls the public `engine.process`, reads `verdict.labels`, and reuses `score_predictions`. `compare_evals` diffs two reports for regression gating. The deployer owns the golden data and the CI gate; LabJury owns the math and the runner. Zero new dependency.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-evaluation-harness-design.md`

## Global Constraints

- Core `dependencies = []`; stdlib only; mechanism in `labjury.evaluation` (core). Core never imports `labjury.contrib`.
- No plugin contract change; `run_evaluation` uses only public `Engine.process` / `ItemResult` / `Verdict`.
- Metrics return raw ratios (no rounding); division-by-zero yields `0.0`, never an error.
- No built-in datasets, no CI integration, no scorer-only eval, no threshold sweeps.
- TDD throughout; commit per task.

## Review Focus

- Worked multi-label example → exact micro P/R, per-label F1, exact-match rate — pinned in Task 1 (`test_worked_example`).
- Division-by-zero is `0.0`: empty report all-zero; a label with no predictions precision `0.0` — pinned in Task 1 (`test_empty_report`, `test_zero_denominators`).
- `compare_evals` flags a micro-F1 drop and lists the regressed label; improvement isn't a regression; tolerance absorbs a small drop — pinned in Task 1 (`test_regression_detected`, `test_improvement_not_regression`, `test_tolerance`).
- `run_evaluation` treats a no-verdict/`FAILED` result as an empty prediction — pinned in Task 2 (`test_failed_result_is_empty_prediction`).
- `run_evaluation` reproduces the `score_predictions` report for the same predictions — pinned in Task 2 (`test_run_evaluation_matches_score_predictions`).

---

### Task 1: Metric core + regression comparison

**Files:**
- Create: `src/labjury/evaluation.py`
- Test: `tests/test_evaluation.py`

**Interfaces:**
- Consumes: nothing from LabJury (pure math).
- Produces:
  - `labjury.evaluation.LabelScore` — frozen: `label: str`, `tp: int = 0`, `fp: int = 0`, `fn: int = 0`; properties `precision`, `recall`, `f1` (each `0.0` on zero denominator).
  - `labjury.evaluation.EvalReport` — frozen: `n_cases: int`, `exact_matches: int`, `per_label: dict[str, LabelScore]`; properties `micro_precision`, `micro_recall`, `micro_f1` (over summed tp/fp/fn), `macro_precision`, `macro_recall`, `macro_f1` (mean of per-label, `0.0` if no labels), `exact_match_rate` (`exact_matches/n_cases`, `0.0` if `n_cases==0`).
  - `labjury.evaluation.score_predictions(pairs: Iterable[tuple[set[str], set[str]]]) -> EvalReport`.
  - `labjury.evaluation.EvalComparison` — frozen: `baseline: EvalReport`, `candidate: EvalReport`, `micro_f1_delta: float`, `macro_f1_delta: float`, `regressed_labels: list[str]`; method `regressed(tolerance: float = 0.0) -> bool` (`micro_f1_delta < -tolerance`).
  - `labjury.evaluation.compare_evals(baseline: EvalReport, candidate: EvalReport) -> EvalComparison`.

- [ ] **Step 1: Write the failing tests** in `tests/test_evaluation.py`

```python
import pytest
from labjury.evaluation import (
    EvalReport, LabelScore, compare_evals, score_predictions,
)


def test_worked_example():
    # Case A: expected {spam,nsfw} predicted {spam}; Case B: expected {spam} predicted {spam,ads}
    report = score_predictions([
        ({"spam", "nsfw"}, {"spam"}),
        ({"spam"}, {"spam", "ads"}),
    ])
    assert report.n_cases == 2
    assert report.per_label["spam"].f1 == 1.0
    assert report.micro_precision == pytest.approx(2 / 3)
    assert report.micro_recall == pytest.approx(2 / 3)
    assert report.micro_f1 == pytest.approx(2 / 3)
    assert report.macro_f1 == pytest.approx(1 / 3)
    assert report.exact_match_rate == 0.0


def test_exact_match_counts():
    report = score_predictions([({"a"}, {"a"}), ({"a"}, {"b"})])
    assert report.exact_matches == 1
    assert report.exact_match_rate == 0.5


def test_empty_report():
    report = score_predictions([])
    assert report.n_cases == 0
    assert report.micro_f1 == 0.0 and report.macro_f1 == 0.0
    assert report.exact_match_rate == 0.0


def test_zero_denominators():
    report = score_predictions([(set(), {"ghost"})])   # only a false positive
    assert report.per_label["ghost"].precision == 0.0
    assert report.per_label["ghost"].recall == 0.0
    assert report.per_label["ghost"].f1 == 0.0


def test_regression_detected():
    base = score_predictions([({"a"}, {"a"}), ({"b"}, {"b"})])          # perfect
    cand = score_predictions([({"a"}, {"a"}), ({"b"}, set())])          # b now missed
    cmp = compare_evals(base, cand)
    assert cmp.micro_f1_delta < 0
    assert cmp.regressed() is True
    assert "b" in cmp.regressed_labels


def test_improvement_not_regression():
    base = score_predictions([({"a"}, set())])
    cand = score_predictions([({"a"}, {"a"})])
    assert compare_evals(base, cand).regressed() is False


def test_tolerance():
    base = score_predictions([({"a"}, {"a"}), ({"a"}, {"a"})])
    cand = score_predictions([({"a"}, {"a"}), ({"a"}, set())])   # micro_f1 drops
    cmp = compare_evals(base, cand)
    assert cmp.regressed(tolerance=0.0) is True
    assert cmp.regressed(tolerance=1.0) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_evaluation.py -v`
Expected: FAIL — `No module named 'labjury.evaluation'`.

- [ ] **Step 3: Implement `src/labjury/evaluation.py` (metric core + regression)**

`LabelScore` with `precision`/`recall`/`f1` properties (guard zero denominators → `0.0`). `EvalReport` storing `n_cases`, `exact_matches`, `per_label`, with micro aggregates summing `tp/fp/fn` across `per_label` and macro aggregates averaging the per-label properties (`0.0` when `per_label` empty), plus `exact_match_rate`. `score_predictions` folds the pairs into mutable per-label counters then freezes them into `LabelScore`s. `EvalComparison` + `compare_evals` computing the two deltas and the `regressed_labels` list (labels in both reports whose candidate per-label F1 is below the baseline's).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_evaluation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/labjury/evaluation.py tests/test_evaluation.py
git commit -m "feat: evaluation metric core (P/R/F1, micro/macro) + regression compare"
```

---

### Task 2: `GoldenCase` + `run_evaluation`

**Files:**
- Modify: `src/labjury/evaluation.py` (add `GoldenCase`, `run_evaluation`)
- Test: `tests/test_evaluation.py` (add cases)

**Interfaces:**
- Consumes: `Item` from `labjury.state`; `score_predictions` (Task 1); the public `engine.process(item) -> ItemResult` with `result.verdict.labels`.
- Produces:
  - `labjury.evaluation.GoldenCase` — frozen: `item: Item`, `expected_labels: frozenset[str]`.
  - `labjury.evaluation.run_evaluation(engine, cases: Iterable[GoldenCase]) -> EvalReport` (async) — for each case, `result = await engine.process(case.item)`, `predicted = set(result.verdict.labels) if result.verdict else set()`, pair `(set(case.expected_labels), predicted)`; return `score_predictions(pairs)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_evaluation.py`

```python
from labjury.evaluation import GoldenCase, run_evaluation
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.state import Item


class _FakeEngine:
    """Returns a verdict with chosen labels per item id; id mapped to None -> FAILED."""
    def __init__(self, labels_by_id):
        self._labels = labels_by_id

    async def process(self, item):
        labels = self._labels.get(item.id)
        if labels is None:
            return ItemResult(item.id, Status.FAILED, error="boom")
        return ItemResult(item.id, Status.DECIDED,
                          verdict=Verdict(Action.BLOCK, list(labels), {}, [], "x"))


async def test_run_evaluation_matches_score_predictions():
    engine = _FakeEngine({"i1": {"spam"}, "i2": {"spam", "ads"}})
    cases = [
        GoldenCase(Item("i1", {}), frozenset({"spam", "nsfw"})),
        GoldenCase(Item("i2", {}), frozenset({"spam"})),
    ]
    report = await run_evaluation(engine, cases)
    expected = score_predictions([
        ({"spam", "nsfw"}, {"spam"}),
        ({"spam"}, {"spam", "ads"}),
    ])
    assert report.per_label.keys() == expected.per_label.keys()
    assert report.micro_f1 == expected.micro_f1
    assert report.n_cases == 2


async def test_failed_result_is_empty_prediction():
    engine = _FakeEngine({"i1": None})     # FAILED -> no verdict
    report = await run_evaluation(engine, [GoldenCase(Item("i1", {}), frozenset({"spam"}))])
    assert report.per_label["spam"].fn == 1
    assert report.per_label["spam"].recall == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_evaluation.py -k "run_evaluation or failed_result" -v`
Expected: FAIL — `cannot import name 'GoldenCase'` / `'run_evaluation'`.

- [ ] **Step 3: Implement `GoldenCase` + `run_evaluation` in `src/labjury/evaluation.py`**

`GoldenCase` frozen dataclass; `run_evaluation` per Interfaces — thin async loop reusing `score_predictions`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_evaluation.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/labjury/evaluation.py tests/test_evaluation.py
git commit -m "feat: GoldenCase + run_evaluation (pipeline eval over a golden set)"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/evaluation.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `LabelScore`, `EvalReport`, `score_predictions`, `GoldenCase`, `run_evaluation`, `EvalComparison`, `compare_evals` (Tasks 1–2, from `labjury.evaluation`).
- Produces: the seven names importable as `labjury.<name>`.

- [ ] **Step 1: Add the seven names to `tests/test_public_api.py`**

Append `"LabelScore"`, `"EvalReport"`, `"score_predictions"`, `"GoldenCase"`, `"run_evaluation"`, `"EvalComparison"`, `"compare_evals"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: LabelScore`.

- [ ] **Step 3: Re-export in `src/labjury/__init__.py`**

Add `from labjury.evaluation import (EvalComparison, EvalReport, GoldenCase, LabelScore, compare_evals, run_evaluation, score_predictions)`; add the seven names to `__all__` under a new `# evaluation` group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Write `docs/evaluation.md` and link it**

`docs/evaluation.md`: why evaluation (accuracy + regression gating); the golden set (`GoldenCase`, the deployer's labeled data — bring your own); `run_evaluation(engine, cases)` → `EvalReport` with a worked example showing per-label and micro/macro P/R/F1 and exact-match rate; `score_predictions` for evaluating predictions you already have; policy regression with `compare_evals` / `EvalComparison.regressed(tolerance)` and how a deployer gates CI on it (assert `not cmp.regressed(tolerance=...)`); the Non-goals (no datasets, no CI integration, pipeline-level not component-level, label-set not action-level). Add "### Evaluation & regression (opt-in)" to `README.md` and "### Đánh giá & regression (tùy chọn)" to `README.vi.md` after the human-review section, each linking the doc.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/evaluation.md README.md README.vi.md
git commit -m "feat: re-export evaluation surface; docs"
```
