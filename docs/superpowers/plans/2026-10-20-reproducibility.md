# Reproducibility (replay verification & drift) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing replay primitives into a first-class reproducibility audit — `verify_replay(event, policy) -> ReplayReport` that replays the policy over a recorded decision's inputs, confirms the verdict reproduces, and detects policy version drift — after moving the `verdict_to_dict`/`provenance_of` helpers from the engine into `audit.py`.

**Architecture:** `verdict_to_dict` and `provenance_of` move from `engine.py` (where they are private `_`-helpers) to `audit.py` (which already owns domain serialization), and the engine imports them back — removing duplication and keeping `audit.py` free of any `engine.py` import. `verify_replay`, `ReplayReport`, and `VersionChange` are added to `audit.py`, composing the existing `replay_decision` + `verdict_matches` with a `(name, version)` diff of the recorded vs current policy provenance. Zero new dependency, pure core, no engine behavior change.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-reproducibility-design.md`

## Global Constraints

- Core `dependencies = []`; stdlib only; mechanism stays in `labjury.audit`. `audit.py` must never import `engine.py` (no cycle).
- No public plugin contract change. New names are additive; the helper move is internal (engine-private helpers used only by the engine).
- Drift compares `(name, version)` only, never `params` — `version` is the plugin's declared reproducibility handle; `params` is config and would be noise.
- `verify_replay` composes `replay_decision`/`verdict_matches` without changing their signatures or semantics; a cache-hit event raises `ValueError` (inherited from `replay_decision`).
- No scorer replay, no rubric-vs-registry check, no `schema_version`, no storage.
- TDD throughout; commit per task.

## Review Focus

- Same policy version + matching verdict → `faithful is True`, `drift == {}` — pinned in Task 2 (`test_faithful_when_version_and_verdict_match`).
- Policy version bumped + verdict still matches → `drift["policy"]` populated, `faithful is False` — pinned in Task 2 (`test_version_drift_detected_even_when_verdict_matches`).
- Verdict differs → `verdict_matches is False`, `faithful is False`, both verdict dicts present — pinned in Task 2 (`test_verdict_mismatch_reported`).
- Cache-hit event → `verify_replay` raises `ValueError` — pinned in Task 2 (`test_verify_replay_of_cache_hit_raises`).
- Engine recorded output unchanged after the helper move — the existing engine/audit suite stays green, run in Task 1 Step 4.

---

### Task 1: Move `verdict_to_dict` / `provenance_of` into `audit.py`

**Files:**
- Modify: `src/labjury/audit.py` (add the two public helpers)
- Modify: `src/labjury/engine.py` (import them; delete the local `_`-versions; update call sites)
- Test: `tests/test_audit.py` (add import/behavior cases)

**Interfaces:**
- Consumes: `Verdict` from `labjury.results` (already imported in `audit.py`); `ProvenanceRef` (defined in `audit.py`).
- Produces:
  - `labjury.audit.verdict_to_dict(v: Verdict) -> dict` — keys `action` (`v.action.value`), `labels`, `scores`, `novel_labels`, `reason`.
  - `labjury.audit.provenance_of(plugin: object) -> ProvenanceRef` — `ProvenanceRef(type(plugin).__name__, getattr(plugin, "version", None), getattr(plugin, "params", None))`.
  - `engine.py` no longer defines `_verdict_to_dict` / `_provenance_of`; it imports and calls `verdict_to_dict` / `provenance_of`.

- [ ] **Step 1: Write the failing tests** in `tests/test_audit.py`

```python
def test_verdict_to_dict_shape():
    from labjury.audit import verdict_to_dict
    from labjury.results import Action, Verdict
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    assert verdict_to_dict(v) == {
        "action": "accept", "labels": ["a"], "scores": {"a": 0.9},
        "novel_labels": [], "reason": "ok",
    }

def test_provenance_of_reads_name_version_params():
    from labjury.audit import provenance_of
    class P:
        version = "1.2"
        params = {"k": 1}
    ref = provenance_of(P())
    assert (ref.name, ref.version, ref.params) == ("P", "1.2", {"k": 1})

def test_provenance_of_defaults_when_missing():
    from labjury.audit import provenance_of
    class Bare: ...
    ref = provenance_of(Bare())
    assert (ref.name, ref.version, ref.params) == ("Bare", None, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_audit.py -k "verdict_to_dict_shape or provenance_of" -v`
Expected: FAIL — `cannot import name 'verdict_to_dict'` / `'provenance_of'` from `labjury.audit`.

- [ ] **Step 3: Add the helpers to `src/labjury/audit.py`**

Add `verdict_to_dict(v: Verdict) -> dict` and `provenance_of(plugin: object) -> ProvenanceRef` (bodies per Interfaces), in the domain-serialization section (near `answer_to_dict`). `Verdict` is already imported.

- [ ] **Step 4: Update `src/labjury/engine.py` to import and use them**

Delete the module-level `_verdict_to_dict` and `_provenance_of` definitions. Add `verdict_to_dict, provenance_of` to the `from labjury.audit import (...)` block. Replace the three call sites (`_verdict_to_dict(cached)`, `_verdict_to_dict(verdict)`, the two `_provenance_of(...)` in the provenance dict) with the imported names.

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS — new helper tests plus the unchanged engine/audit suite (recorded output byte-identical).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/audit.py src/labjury/engine.py tests/test_audit.py
git commit -m "refactor: move verdict_to_dict/provenance_of into audit (DRY, no cycle)"
```

---

### Task 2: `verify_replay` + `ReplayReport` + `VersionChange`

**Files:**
- Modify: `src/labjury/audit.py` (add the value objects + `verify_replay`)
- Test: `tests/test_audit.py` (add cases)

**Interfaces:**
- Consumes: `replay_decision`, `verdict_matches`, `verdict_to_dict`, `provenance_of`, `ProvenanceRef`, `AuditEvent` (all in `audit.py` after Task 1).
- Produces:
  - `labjury.audit.VersionChange` — frozen dataclass: `recorded: str | None`, `current: str | None`.
  - `labjury.audit.ReplayReport` — frozen dataclass: `verdict_matches: bool`, `drift: dict[str, VersionChange]`, `recorded_verdict: dict | None`, `replayed_verdict: dict`; property `faithful -> bool` = `verdict_matches and not drift`.
  - `labjury.audit.verify_replay(event: AuditEvent, policy) -> ReplayReport` (async): replays via `replay_decision` (propagates its cache-hit `ValueError`), sets `verdict_matches` via `verdict_matches(event, replayed)`, and populates `drift["policy"] = VersionChange("Name@ver", "Name@ver")` when the event's `provenance["policy"]` differs in name or version from `provenance_of(policy)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_audit.py`

Build an `AuditEvent` whose `provenance={"policy": provenance_of(recorded_policy)}` and whose `verdict=verdict_to_dict(known_verdict)`; use a fake policy returning a fixed `Verdict`. Fakes: `_FixedPolicy(verdict, *, version=None)` with a `.decide(...)` returning `verdict` and an optional `version` attr.

```python
async def test_faithful_when_version_and_verdict_match():
    from labjury.audit import verify_replay, provenance_of, verdict_to_dict
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    policy = _FixedPolicy(v, version="1.0")
    event = AuditEvent("i1", "fp", provenance={"policy": provenance_of(policy)},
                       verdict=verdict_to_dict(v))
    report = await verify_replay(event, _FixedPolicy(v, version="1.0"))
    assert report.verdict_matches is True
    assert report.drift == {}
    assert report.faithful is True

async def test_version_drift_detected_even_when_verdict_matches():
    from labjury.audit import verify_replay, provenance_of, verdict_to_dict
    v = Verdict(Action.ACCEPT, ["a"], {"a": 0.9}, [], "ok")
    event = AuditEvent("i1", "fp",
                       provenance={"policy": provenance_of(_FixedPolicy(v, version="1.0"))},
                       verdict=verdict_to_dict(v))
    report = await verify_replay(event, _FixedPolicy(v, version="2.0"))
    assert report.verdict_matches is True
    assert "policy" in report.drift
    assert report.drift["policy"].recorded.endswith("@1.0")
    assert report.drift["policy"].current.endswith("@2.0")
    assert report.faithful is False

async def test_verdict_mismatch_reported():
    from labjury.audit import verify_replay, provenance_of, verdict_to_dict
    recorded_v = Verdict(Action.ACCEPT, ["a"], {}, [], "ok")
    other_v = Verdict(Action.REJECT, [], {}, [], "no")
    event = AuditEvent("i1", "fp",
                       provenance={"policy": provenance_of(_FixedPolicy(recorded_v, version="1.0"))},
                       verdict=verdict_to_dict(recorded_v))
    report = await verify_replay(event, _FixedPolicy(other_v, version="1.0"))
    assert report.verdict_matches is False
    assert report.faithful is False
    assert report.recorded_verdict["action"] == "accept"
    assert report.replayed_verdict["action"] == "reject"

async def test_verify_replay_of_cache_hit_raises():
    from labjury.audit import verify_replay
    v = Verdict(Action.ACCEPT, [], {}, [], "cached")
    event = AuditEvent("i1", "fp", from_cache=True, verdict=verdict_to_dict(v))
    with pytest.raises(ValueError):
        await verify_replay(event, _FixedPolicy(v))
```

(Add a `_FixedPolicy` fake near the top of the module if not present; `verdict_to_dict`/`provenance_of` imported from `labjury.audit`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_audit.py -k "faithful or drift or verdict_mismatch or verify_replay_of_cache_hit" -v`
Expected: FAIL — `cannot import name 'verify_replay'`.

- [ ] **Step 3: Implement the value objects + `verify_replay` in `src/labjury/audit.py`**

`VersionChange` and `ReplayReport` frozen dataclasses (with the `faithful` property) in the replay section; `verify_replay` per Interfaces — `await replay_decision(event, policy)` first (so cache-hit raises before anything else), then `verdict_matches`, then the `(name, version)` diff building `drift`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_audit.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/labjury/audit.py tests/test_audit.py
git commit -m "feat: verify_replay + ReplayReport — reproduction check with version-drift detection"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/reproducibility.md`
- Modify: `docs/audit-trail.md` (cross-link), `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `verify_replay`, `ReplayReport`, `VersionChange` (Task 2, from `labjury.audit`).
- Produces: the three names importable as `labjury.<name>`.

- [ ] **Step 1: Add the three names to `tests/test_public_api.py`**

Append `"verify_replay"`, `"ReplayReport"`, `"VersionChange"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: verify_replay`.

- [ ] **Step 3: Re-export the names in `src/labjury/__init__.py`**

Add `ReplayReport`, `VersionChange`, `verify_replay` to the `from labjury.audit import (...)` block; add the three to `__all__` in the `# audit` group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Write `docs/reproducibility.md` and link it**

`docs/reproducibility.md`: the reproducibility question for a decision system; what the audit event already pins (inputs, rubric_version, taxonomy snapshot, provenance); `verify_replay` and `ReplayReport` (the `faithful`/`verdict_matches`/`drift` tri-state) with a worked example; why only the policy stage is replayed (scorer pinned by recorded answers); why drift is `(name, version)` not params; and the documented extensions (rubric-vs-registry check via `RubricStore.get`, scorer manifest). Add "### Reproducibility & replay (opt-in)" to `README.md` and "### Tái lập & replay (tùy chọn)" to `README.vi.md` after the rubric-registry section, each linking the doc. Add a one-line cross-link from `docs/audit-trail.md` to `docs/reproducibility.md`.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/reproducibility.md docs/audit-trail.md README.md README.vi.md
git commit -m "feat: re-export reproducibility surface; docs"
```
