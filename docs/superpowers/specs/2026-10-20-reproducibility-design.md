# Reproducibility — replay verification & version-drift detection

**Status:** design (CTO-decided; owner delegated design authority, "làm luôn đi" 2026-10-20) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness **Tier 2** (operability at scale), **item 2 of 5** — reproducibility/versioning. Builds directly on item 1 (the rubric registry's `Candidate.rubric_version` handle) and on the Tier-1 audit trail.

## Intent and the why

LabJury already *records* everything a decision needs to be reproduced: an
`AuditEvent` carries the candidates (each with its `Question` and, since item 1,
its `rubric_version`), the answers, the taxonomy snapshot (`known_labels`), the
verdict, and the provenance of the scorer and policy (`ProvenanceRef` =
name + version + params). It also already has the raw replay primitive
`replay_decision(event, policy)` which re-runs a policy over those recorded
inputs.

What is missing is the *verification*. Today an auditor must call
`replay_decision`, then separately call `verdict_matches`, and there is **no
detection of version drift** — if the policy that produced a historical decision
has since been replaced or version-bumped, replaying with the current policy
silently uses the new one, and nothing tells you the pipeline changed. For a
decision system whose enterprise value is governance and reproducibility, "did
this decision reproduce, and is the pipeline that reproduces it the same one that
made it?" must be a single, first-class answer.

This slice turns the existing primitives into one reproducibility audit:
**`verify_replay`** re-runs the policy, compares the verdict, and diffs the
recorded component version against the current one, returning a structured
**`ReplayReport`**. It operationalizes the versioning data the framework already
records — it adds a *mechanism to check*, not new data to store.

## Goals

- **`verdict_to_dict` and `provenance_of` move from `engine.py` to `audit.py`**
  (public, un-underscored). The audit module already owns domain-object
  serialization (`question_to_dict`, `candidate_to_dict`, `answer_to_dict`);
  verdict serialization and "provenance of a plugin" belong there too. The engine
  imports them back. This removes the duplication `verify_replay` would otherwise
  create and keeps `audit.py` free of any import of `engine.py` (no cycle).
  - `verdict_to_dict(v: Verdict) -> dict` — the existing shape
    (`action`/`labels`/`scores`/`novel_labels`/`reason`).
  - `provenance_of(plugin: object) -> ProvenanceRef` — `type(plugin).__name__`,
    `getattr(plugin, "version", None)`, `getattr(plugin, "params", None)`.
- **`VersionChange`** (frozen value object): `recorded: str | None`,
  `current: str | None` — a human-readable `"Name@version"` on each side for one
  drifted component.
- **`ReplayReport`** (frozen value object):
  - `verdict_matches: bool` — did the replayed verdict equal the recorded one
    (by `verdict_matches`' existing fields: action, labels, novel_labels, reason)?
  - `drift: dict[str, VersionChange]` — component name → change, containing **only**
    components whose recorded `(name, version)` differs from the current one
    (empty = no drift).
  - `recorded_verdict: dict | None`, `replayed_verdict: dict` — both for inspection
    (a caller can diff scores, which `verdict_matches` omits).
  - `faithful` (property): `verdict_matches and not drift` — a trustworthy
    reproduction: same inputs, same component version, same verdict.
- **`verify_replay(event: AuditEvent, policy) -> ReplayReport`** (async, in `audit.py`):
  replays via `replay_decision` (so a cache-hit event raises `ValueError`, same as
  today — there is no decision to verify, verify the original), compares with
  `verdict_matches`, and compares the event's `provenance["policy"]` against
  `provenance_of(policy)`; a differing `name` or `version` populates
  `drift["policy"]`.
- **Public surface:** re-export `verify_replay`, `ReplayReport`, `VersionChange`
  from `labjury`; add to `test_public_api.py`.
- **Docs:** `docs/reproducibility.md` + bilingual README pointers; cross-link from
  `docs/audit-trail.md`.

## Non-goals / anti-goals

- **No scorer replay.** The scorer stage is non-deterministic and remote; its
  output is already *pinned* as the recorded `answers`, so replay uses those and
  the policy is the only live stage. `verify_replay` therefore verifies the policy
  stage. (Scorer version is still recorded in provenance for the manifest; it is
  simply not something replay can re-execute.)
- **No rubric-vs-registry drift check in this slice.** With item 1, each candidate
  records its `rubric_version` and its `Question`; cross-checking those against a
  live `RubricStore` (`get(label, version)` and compare the question) is the
  natural extension and is documented as such, but it widens the surface (an
  optional `RubricStore` param, an `audit → plugins` import) past one solid slice.
- **No `schema_version` on `AuditEvent`.** Forward-compat of the stored record
  format is a separate versioning concern; not this slice.
- **No engine behavior change.** Moving two pure helper functions out of the engine
  is a refactor; the engine records exactly what it recorded before.
- **No change to `replay_decision` / `verdict_matches` signatures or semantics.**
  `verify_replay` composes them.
- **No new dependency, no storage.** Pure-core, stdlib only.

## Constraints (inherited)

- Core `dependencies = []`; stdlib only; mechanism stays in `labjury.audit`
  (core). `audit.py` must not import `engine.py`.
- No public plugin contract change. `ReplayReport`/`VersionChange`/`verify_replay`
  are additive; the `verdict_to_dict`/`provenance_of` move is internal (they were
  engine-private `_`-helpers, used only by the engine).
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### Moved helpers (`audit.py`)

```python
def verdict_to_dict(v: Verdict) -> dict: ...
def provenance_of(plugin: object) -> ProvenanceRef: ...
```

`engine.py` replaces its local `_verdict_to_dict` / `_provenance_of` with imports
of these and updates its three call sites. The dicts and provenance recorded are
byte-identical to before (verified by the unchanged engine/audit tests).

### `verify_replay` (`audit.py`)

```python
@dataclass(frozen=True)
class VersionChange:
    recorded: str | None
    current: str | None

@dataclass(frozen=True)
class ReplayReport:
    verdict_matches: bool
    drift: dict[str, VersionChange]
    recorded_verdict: dict | None
    replayed_verdict: dict
    @property
    def faithful(self) -> bool:
        return self.verdict_matches and not self.drift

async def verify_replay(event: AuditEvent, policy) -> ReplayReport:
    replayed = await replay_decision(event, policy)   # raises on cache-hit
    matches = verdict_matches(event, replayed)
    drift: dict[str, VersionChange] = {}
    recorded = event.provenance.get("policy")
    current = provenance_of(policy)
    if recorded is not None and (recorded.name != current.name or recorded.version != current.version):
        drift["policy"] = VersionChange(
            f"{recorded.name}@{recorded.version}", f"{current.name}@{current.version}"
        )
    return ReplayReport(matches, drift, event.verdict, verdict_to_dict(replayed))
```

**Why compare `(name, version)` and not `params`:** `version` is the plugin's
declared reproducibility handle by contract — a behavior change is expected to
bump it. `params` is configuration; folding it into drift would flag every benign
config tweak and drown the signal. Documented so a deployer knows version is the
contract.

### Public surface

Re-exported from `labjury` under the audit group: `verify_replay`, `ReplayReport`,
`VersionChange`. Added to `test_public_api.py`.

## What's left to the builder

- Exact `"Name@version"` spelling in `VersionChange` (fixed above; tests pin it).
- Whether `drift` omits non-drifted components (yes — only drifted entries appear)
  is specified; the internal construction is the builder's.
- Test fixtures (a fake policy with a `version` attr, an `AuditEvent` with a
  recorded policy provenance).

## Review focus (inputs the tests must pin)

- **Same policy version, matching verdict → `faithful is True`, `drift == {}`** —
  the happy path of a trustworthy reproduction.
- **Policy version bumped since the decision → `drift["policy"]` populated,
  `faithful is False`** even if the verdict still matches (the whole point of drift
  detection).
- **Verdict no longer matches → `verdict_matches is False`, `faithful is False`**,
  with both recorded and replayed verdict dicts present for inspection.
- **A cache-hit event → `verify_replay` raises `ValueError`** (nothing to verify;
  same contract as `replay_decision`).
- **Engine output unchanged after the helper move** — the existing engine/audit
  suite stays green (byte-identical recorded dicts/provenance).
