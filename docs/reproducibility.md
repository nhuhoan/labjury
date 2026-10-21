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

## Rubric drift — `rubric_drift`

`verify_replay` checks the *policy* stage. A decision also depends on the
**rubric** — the `Question` asked about each label, which a proposer optionally
sources from a [`RubricStore`](rubric-registry.md) and records as the candidate's
`rubric_version`. `rubric_drift` confirms those recorded rubrics still match the
registry:

```python
drift = await lj.rubric_drift(event, store)   # list[RubricDrift]; [] == consistent
```

For each recorded candidate carrying a `rubric_version`, it fetches
`await store.get(label, version)` and compares the recorded question to the
registry's. A published `(label, version)` is immutable by contract, so any
mismatch is a real signal, reported as one `RubricDrift(label, version, reason,
recorded_question, registry_question)` with `reason` either:

- `"version absent from registry"` — the version isn't in this registry
  (`registry_question is None`): you are checking against a *different* registry
  than the one that made the decision, or it was rebuilt;
- `"question differs from registry"` — the version exists but its question
  changed.

Candidates without a `rubric_version` are skipped (they weren't sourced from a
registry), and a cache-hit or no-candidate event yields `[]`. Like
`verify_replay`, this is **detection only** — what to do about drift (alert,
quarantine, re-decide) is the deployer's.

## Extensions (not in core yet)

- **Scorer manifest comparison.** The recorded scorer provenance can be surfaced
  alongside the report for teams that track model versions out of band.
