# Evaluation & regression

A moderation/labeling pipeline that silently regresses ships wrong decisions at
scale. The evaluation harness answers two questions: **is it accurate?** and **did
my last change make it worse?** LabJury owns the measurement mechanism — it does not
ship golden datasets (that is your labeled data, in your domain) and does not run
your CI; you call these functions from your own pipeline. The math is pure,
deterministic, and zero-dependency.

## Golden set + `run_evaluation`

A golden set is ground truth — items paired with the labels a correct pipeline
should emit:

```python
import labjury as lj

golden = [
    lj.GoldenCase(lj.Item("post-1", {"text": "…"}), frozenset({"spam"})),
    lj.GoldenCase(lj.Item("post-2", {"text": "…"}), frozenset({"nsfw", "violence"})),
    …
]

report = await lj.run_evaluation(engine, golden)
report.micro_f1, report.macro_f1          # aggregate quality
report.per_label["spam"].precision        # where it is weak
report.exact_match_rate                   # fraction of items labeled exactly right
```

`run_evaluation` runs each case through the public `engine.process`, reads the
verdict's labels, and scores them. A result with no verdict (e.g. a `FAILED` item)
is scored as an empty prediction — a pipeline that fails to decide earns no credit.

## Metrics

Metrics are over the verdict **label set** — the decision that actually ships. For
each label the harness counts true/false positives and false negatives, then:

- **precision / recall / F1** per label (`report.per_label[label]`);
- **micro** aggregates (over summed counts — weights by frequency);
- **macro** aggregates (mean of the per-label scores — weights every label equally);
- **exact-match rate** (the fraction of items whose predicted set equals the
  expected set).

Every ratio is `0.0` when its denominator is zero (an empty report, a never-predicted
label) — never an error. Raw ratios are returned; round them yourself for display.

If you already have predictions (not an engine to run), score them directly:

```python
report = lj.score_predictions([
    ({"spam", "nsfw"}, {"spam"}),     # (expected, predicted)
    ({"spam"}, {"spam", "ads"}),
])
```

## Policy regression

Run the harness before and after a change (a new policy version, a reworded rubric,
a different model) and compare:

```python
baseline = await lj.run_evaluation(old_engine, golden)
candidate = await lj.run_evaluation(new_engine, golden)

cmp = lj.compare_evals(baseline, candidate)
cmp.micro_f1_delta        # negative = overall quality dropped
cmp.regressed_labels      # which labels got worse

# gate your CI on it:
assert not cmp.regressed(tolerance=0.01), f"regression: {cmp.regressed_labels}"
```

`EvalComparison.regressed(tolerance)` is `True` when micro-F1 dropped by more than
`tolerance`. LabJury returns the numbers; the gate (how much drop you tolerate, where
you assert) is yours.

## Action-level evaluation

Labels are one view; the decision that actually *ships* is the **action** —
`ACCEPT` / `BLOCK` / `REVIEW`. A pipeline can get labels right yet route the wrong
action (e.g. the policy sends too much to `REVIEW`). Score the action directly:

```python
from labjury.results import Action

golden = [lj.GoldenCase(item, frozenset({"nsfw"}), expected_action=Action.BLOCK), ...]
report = await lj.run_action_evaluation(engine, golden)

report.accuracy                       # fraction routed to the right action
report.confusion[("block", "review")] # how many BLOCKs were sent to REVIEW instead
report.per_action["block"].recall     # of the things that should BLOCK, how many did
```

`run_action_evaluation` requires every case to carry an `expected_action` (it raises
otherwise). `ActionReport` holds:

- `confusion` — a matrix keyed by `(expected_action, predicted_action)` value
  strings. A `FAILED` item (no verdict) predicts the bucket `"none"`, so a pipeline
  that fails to decide is never scored correct.
- `accuracy` — the diagonal over all cases.
- `per_action` — one-vs-rest `LabelScore` per real action (`precision`/`recall`/`f1`),
  the same math as the label metrics.

The pure core is `lj.score_actions(pairs)` over `(expected, predicted)` `Action`
pairs (predicted `None` = no action) if you already have predictions. The confusion
is reported raw — **cost-weighting** it (a missed `BLOCK` usually costs more than a
spurious `REVIEW`) is your policy over these counts. This is additive to the label
path; `run_evaluation` and `score_predictions` are unchanged.

## Non-goals

- **No built-in golden datasets.** Bring your own labeled data and storage.
- **No CI integration.** `compare_evals` / `regressed` return values; you assert on
  them in your pipeline.
- **Pipeline-level, not component-level.** The harness scores the end-to-end verdict
  labels and action, not a scorer or proposer in isolation.
- **No cost-weighting of the action confusion.** `ActionReport` reports raw counts;
  what a misroute costs is your policy.
