# Reproducibility — replay verification & version drift

For a decision system the enterprise question is not "how fast" but "can you
*prove* why this decision happened, and show that the pipeline which reproduces it
is the same one that made it?" LabJury answers both with the audit trail plus one
verification call.

## What a decision already pins

Every `AuditEvent` (see [audit-trail.md](audit-trail.md)) records the full input to
one decision:

- the **candidates** — each with its `Question` and, since the rubric registry,
  its [`rubric_version`](rubric-registry.md);
- the **answers** the scorer returned;
- the **taxonomy snapshot** (`known_labels`) in force at decision time;
- the **verdict**; and
- the **provenance** of the scorer and policy — `ProvenanceRef(name, version,
  params)`.

That is everything needed to re-run the *deterministic* half of the pipeline.

## `verify_replay`

```python
import labjury as lj

report = await lj.verify_replay(event, current_policy)

report.verdict_matches   # did replaying the policy reproduce the recorded verdict?
report.drift             # {"policy": VersionChange(recorded="RecallBiasedPolicy@1.0",
                         #                           current="RecallBiasedPolicy@2.0")}
report.faithful          # verdict_matches AND no drift → a trustworthy reproduction
report.recorded_verdict  # the stored verdict dict (inspect scores etc.)
report.replayed_verdict  # the freshly replayed verdict dict
```

`verify_replay` re-runs the policy over the event's recorded inputs, checks the
replayed verdict against the recorded one, and diffs the policy version recorded on
the event against the policy you hand it. `ReplayReport.faithful` is the one-line
answer an auditor wants: **same inputs, same policy version, same verdict.**

The three outcomes are distinct on purpose:

| `verdict_matches` | `drift` | `faithful` | meaning |
|---|---|---|---|
| `True` | `{}` | `True` | reproduced, and by the same policy version — trust it |
| `True` | non-empty | `False` | verdict still matches, but the policy version changed since — reproduced *by luck of this input*, not guaranteed in general |
| `False` | any | `False` | the policy no longer produces this verdict — behavior changed; inspect `recorded_verdict` vs `replayed_verdict` |

A **cache-hit event** has no decision of its own to verify, so `verify_replay`
raises `ValueError` — verify the original decision's event instead (same contract
as `replay_decision`).

## Why only the policy is replayed

The scorer stage (Jev, an LLM judge, ASR) is remote and non-deterministic, so
replaying it would not be reproducible. It does not need to be: the scorer's
output is **pinned** as the recorded `answers`, and replay feeds those to the
policy. The policy — the stage that turns answers into a verdict — is the
deterministic part, and it is what `verify_replay` re-executes. The scorer's
version is still recorded in provenance as part of the decision's manifest; it is
simply not something replay re-runs.

## Why drift is `(name, version)`, not `params`

A plugin's `version` is its declared reproducibility handle: a change in behavior
is expected to bump it. `params` is configuration — folding every benign param
tweak into the drift signal would drown the one that matters. So drift compares
the class name and the version string. If you change what a policy *does*, bump its
`version`, and `verify_replay` will catch any historical decision that no longer
reproduces under the new version.

## Extensions (not in core yet)

- **Rubric-vs-registry check.** Each candidate records its `rubric_version`; a
  fuller audit can confirm those still match a live `RubricStore`
  (`await store.get(label, version)` and compare the `Question`). Because a
  published rubric version is immutable, a mismatch means you are checking against
  a *different* registry than the one that made the decision — a useful
  cross-environment consistency signal.
- **Scorer manifest comparison.** The recorded scorer provenance can be surfaced
  alongside the report for teams that track model versions out of band.
