# Action-level evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship action-level scoring in `labjury.evaluation` — `score_actions` + `ActionReport` (confusion matrix, accuracy, one-vs-rest per-action metrics reusing `LabelScore`), an additive optional `GoldenCase.expected_action`, and `run_action_evaluation`; the label path is untouched.

**Architecture:** A parallel, additive capability beside the existing label scoring. `score_actions` is the pure core (analog of `score_predictions`); it reuses `LabelScore`/`_ratio`. `GoldenCase` gains one defaulted field; `run_action_evaluation` reads `result.verdict.action` via the public engine API.

**Tech Stack:** Python 3.11+ stdlib; pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-10-21-action-eval-design.md`

## Global Constraints

- Pure core, `dependencies = []`; lives in `labjury.evaluation`; reuses `LabelScore`/`_ratio`.
- Label path (`score_predictions`/`run_evaluation`/`EvalReport`/`compare_evals`) untouched.
- `GoldenCase.expected_action` is additive-optional (default None) — positional `GoldenCase(item, labels)` stays valid.
- Re-exported top-level (`ActionReport`, `score_actions`, `run_action_evaluation`) — additive to `__all__`.
- TDD throughout; commit per task.

## Review Focus

- All-correct → `accuracy == 1.0`, per-action `f1 == 1.0` — Task 1 (`test_all_correct`).
- Misroute (expected BLOCK, predicted REVIEW) → off-diagonal; recall/precision drop — Task 1 (`test_misroute`).
- `predicted is None` → `"none"` bucket, fn for expected, never tp — Task 1 (`test_none_predicted_is_failure`).
- `run_action_evaluation` maps no-verdict → None; raises on missing `expected_action` — Task 2 (`test_run_action_eval`, `test_missing_expected_action_raises`).
- Empty → `accuracy == 0.0`, empty `per_action` — Task 1 (`test_empty`).

---

### Task 1: `score_actions` + `ActionReport`

**Files:**
- Modify: `src/labjury/evaluation.py` (add `ActionReport`, `score_actions`)
- Test: `tests/test_evaluation.py` (add action-scoring cases)

**Interfaces:**
- Consumes: `Action` from `labjury.results`; existing `LabelScore`, `_ratio`.
- Produces:
  - `labjury.evaluation.ActionReport` — frozen: `n_cases: int`, `confusion: dict[tuple[str, str], int]`, `per_action: dict[str, LabelScore]`; property `accuracy` (= sum of `confusion[(a, a)]` over real actions / `n_cases`, `0.0` if no cases).
  - `labjury.evaluation.score_actions(pairs: Iterable[tuple[Action, Action | None]]) -> ActionReport`.

- [ ] **Step 1: Write the failing tests** in `tests/test_evaluation.py`

```python
def test_all_correct():
    from labjury.evaluation import score_actions
    from labjury.results import Action
    r = score_actions([(Action.BLOCK, Action.BLOCK), (Action.ACCEPT, Action.ACCEPT)])
    assert r.accuracy == 1.0
    assert r.per_action["block"].f1 == 1.0
    assert r.per_action["accept"].f1 == 1.0


def test_misroute():
    from labjury.evaluation import score_actions
    from labjury.results import Action
    # expected BLOCK but predicted REVIEW
    r = score_actions([(Action.BLOCK, Action.REVIEW)])
    assert r.confusion[("block", "review")] == 1
    assert r.accuracy == 0.0
    assert r.per_action["block"].recall == 0.0   # the BLOCK was missed
    assert r.per_action["block"].fn == 1


def test_none_predicted_is_failure():
    from labjury.evaluation import score_actions
    from labjury.results import Action
    r = score_actions([(Action.BLOCK, None)])
    assert r.confusion[("block", "none")] == 1
    assert r.per_action["block"].fn == 1
    assert r.per_action["block"].tp == 0
    assert "none" not in r.per_action          # "none" is not a real class


def test_empty():
    from labjury.evaluation import score_actions
    r = score_actions([])
    assert r.accuracy == 0.0 and r.per_action == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_evaluation.py -k "all_correct or misroute or none_predicted or test_empty" -v`
Expected: FAIL — `cannot import name 'score_actions'`.

- [ ] **Step 3: Implement in `src/labjury/evaluation.py`**

`ActionReport` frozen dataclass per Interfaces; `accuracy` = `_ratio(sum(self.confusion.get((a, a), 0) for a in real_actions), self.n_cases)` where `real_actions` = the set of expected action values (keys' first element). `score_actions`: iterate pairs, `n_cases += 1`, `e = expected.value`, `p = predicted.value if predicted is not None else "none"`, `confusion[(e, p)] += 1`. Build `per_action` over the real expected action values: for each such `a`, `tp = confusion.get((a, a), 0)`, `fp = sum(n for (ee, pp), n in confusion.items() if pp == a and ee != a)`, `fn = sum(n for (ee, pp), n in confusion.items() if ee == a and pp != a)`; `LabelScore(a, tp, fp, fn)`.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_evaluation.py -k "all_correct or misroute or none_predicted or test_empty" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/labjury/evaluation.py tests/test_evaluation.py
git commit -m "feat: score_actions + ActionReport — action-level confusion metrics"
```

---

### Task 2: `GoldenCase.expected_action` + `run_action_evaluation`

**Files:**
- Modify: `src/labjury/evaluation.py` (`GoldenCase` field; `run_action_evaluation`)
- Modify: `src/labjury/__init__.py` (re-export `ActionReport`, `score_actions`, `run_action_evaluation`; add to `__all__`)
- Test: `tests/test_evaluation.py` (runner cases)

**Interfaces:**
- Consumes: `GoldenCase` (now with `expected_action: Action | None = None`); `score_actions` (Task 1); a duck-typed engine with `async process(item) -> ItemResult`.
- Produces: `labjury.evaluation.run_action_evaluation(engine, cases: Iterable[GoldenCase]) -> ActionReport`.

- [ ] **Step 1: Write the failing tests** in `tests/test_evaluation.py`

```python
async def test_run_action_eval():
    from labjury.evaluation import GoldenCase, run_action_evaluation
    from labjury.results import Action, ItemResult, Status, Verdict
    from labjury.state import Item

    class _Engine:
        async def process(self, item):
            if item.id == "fail":
                return ItemResult("fail", Status.FAILED)
            v = Verdict(Action.BLOCK, ["nsfw"], {}, [], "r")
            return ItemResult(item.id, Status.DECIDED, v)

    cases = [
        GoldenCase(Item("ok", {}), frozenset(), expected_action=Action.BLOCK),
        GoldenCase(Item("fail", {}), frozenset(), expected_action=Action.BLOCK),
    ]
    r = await run_action_evaluation(_Engine(), cases)
    assert r.confusion[("block", "block")] == 1
    assert r.confusion[("block", "none")] == 1     # FAILED -> no action
    assert r.per_action["block"].tp == 1 and r.per_action["block"].fn == 1


async def test_missing_expected_action_raises():
    import pytest
    from labjury.evaluation import GoldenCase, run_action_evaluation
    from labjury.state import Item

    class _Engine:
        async def process(self, item):
            raise AssertionError("should raise before processing")

    with pytest.raises(ValueError):
        await run_action_evaluation(_Engine(), [GoldenCase(Item("i", {}), frozenset())])
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_evaluation.py -k "run_action_eval or missing_expected_action" -v`
Expected: FAIL — `cannot import name 'run_action_evaluation'` (and/or `GoldenCase` has no `expected_action`).

- [ ] **Step 3: Implement in `src/labjury/evaluation.py`**

Add `expected_action: Action | None = None` to `GoldenCase` (import `Action`). `run_action_evaluation`: for each case, if `case.expected_action is None` raise `ValueError("GoldenCase.expected_action is required for action evaluation")`; else `result = await engine.process(case.item)`, `predicted = result.verdict.action if result.verdict else None`, collect `(case.expected_action, predicted)`; return `score_actions(pairs)`.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_evaluation.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Re-export** — add `ActionReport`, `score_actions`, `run_action_evaluation` to the `labjury.evaluation` import block and the `# evaluation` group of `__all__` in `src/labjury/__init__.py`.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS; `PYTHONPATH=src python -c "import labjury; labjury.score_actions; labjury.ActionReport; labjury.run_action_evaluation"`.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/evaluation.py src/labjury/__init__.py tests/test_evaluation.py
git commit -m "feat: run_action_evaluation + GoldenCase.expected_action — golden action eval"
```

---

### Task 3: Docs

**Files:**
- Modify: `docs/evaluation.md` (add an "Action-level evaluation" subsection)
- Modify: `README.md`, `README.vi.md` (one-line pointer in the evaluation area)

**Interfaces:**
- Consumes: `score_actions`, `run_action_evaluation`, `ActionReport` (Tasks 1–2).

- [ ] **Step 1: Document in `docs/evaluation.md`**

An "Action-level evaluation" subsection: why the shipped action matters alongside labels; `score_actions(pairs)` and `ActionReport` (confusion matrix keyed by `(expected, predicted)`, `accuracy`, one-vs-rest `per_action` `LabelScore`); the `None`/`"none"` failure bucket; `GoldenCase(expected_action=...)` + `run_action_evaluation(engine, cases)`; that it is additive to the label path and that cost-weighting the confusion is the deployer's.

- [ ] **Step 2: README pointers**

In the evaluation area of `README.md`, add a sentence that the shipped action (ACCEPT/BLOCK/REVIEW) is scorable too via `lj.score_actions` / `lj.run_action_evaluation`; mirror in `README.vi.md`.

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src pytest`
Expected: PASS (docs-only).

- [ ] **Step 4: Commit**

```bash
git add docs/evaluation.md README.md README.vi.md
git commit -m "docs: action-level evaluation in evaluation + README pointers"
```
