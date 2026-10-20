# SemVer + Plugin Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give LabJury a declared version and a self-guarding public contract (`labjury.__version__` synced to `pyproject`, `__all__` as the enforced surface, exported protocols proven `@runtime_checkable`) plus a stage-plugin conformance checker (`assert_plugin_conforms`), with a compatibility-policy doc.

**Architecture:** `__version__` is a constant in `labjury/__init__.py`, kept in sync with `pyproject.toml` by a `tomllib`-based test. The public-API test becomes a SemVer guard: it iterates `__all__`, checks a curated core set remains public, and verifies exported protocols are runtime-checkable. `assert_plugin_conforms(obj, protocol)` ships in `labjury.testing` and adds the async-ness and capability-type checks that a bare `isinstance` misses. Zero new dependency; pure additions.

**Tech Stack:** Python 3.11+, stdlib only (`tomllib`, `inspect`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-semver-conformance-design.md`

## Global Constraints

- Core `dependencies = []`; stdlib only; conformance helper in `labjury.testing`. Core never imports `labjury.contrib`.
- No change to any plugin contract, protocol, or public signature — this slice only adds `__version__`, a conformance helper, tests, and a doc.
- `__version__` is the single source in the package; the test guards it against `pyproject`.
- No release automation, no CHANGELOG generator, no broad governance docs (separate Tier-3 item).
- TDD throughout; commit per task.

## Review Focus

- `labjury.__version__` equals the `pyproject` version — pinned in Task 1 (`test_version_matches_pyproject`).
- Every `__all__` name importable; curated core ⊆ `__all__` — pinned in Task 1 (`test_public_surface_importable`, `test_core_names_remain_public`).
- Exported stage protocols are `@runtime_checkable` — pinned in Task 1 (`test_exported_protocols_are_runtime_checkable`).
- `assert_plugin_conforms` passes a valid plugin and fails non-async / wrong-typed accepts / missing method — pinned in Task 2.

---

### Task 1: `__version__` + self-guarding public surface

**Files:**
- Modify: `src/labjury/__init__.py` (add `__version__`, export it)
- Create: `tests/test_version.py`
- Modify: `tests/test_public_api.py` (SemVer guard)

**Interfaces:**
- Produces: `labjury.__version__: str` (in `__all__`).

- [ ] **Step 1: Write the failing tests**

`tests/test_version.py`:

```python
import tomllib
from pathlib import Path

import labjury


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert labjury.__version__ == data["project"]["version"]
```

Rewrite `tests/test_public_api.py::test_public_surface_importable` and add two tests:

```python
_MUST_REMAIN_PUBLIC = {
    "Engine", "Item", "State", "Content",
    "ContextBuilder", "Proposer", "Scorer", "DecisionPolicy", "Sink", "Cache",
    "Observer", "TaxonomyStore", "AuditLog",
    "register", "get", "available", "load_entry_points",
    "__version__",
}


def test_public_surface_importable():
    for name in lj.__all__:
        assert hasattr(lj, name), f"{name} in __all__ but not importable"


def test_core_names_remain_public():
    missing = _MUST_REMAIN_PUBLIC - set(lj.__all__)
    assert not missing, f"core public names dropped from __all__: {missing}"


def test_exported_protocols_are_runtime_checkable():
    for name in ["ContextBuilder", "Proposer", "Scorer", "DecisionPolicy",
                 "Sink", "Cache", "Observer", "TaxonomyStore", "AuditLog",
                 "RubricStore", "Redactor", "Guard", "ReviewQueue"]:
        proto = getattr(lj, name)
        assert getattr(proto, "_is_runtime_protocol", False), f"{name} must be @runtime_checkable"
```

(Keep the existing `test_full_pipeline_runs_without_jev`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_version.py tests/test_public_api.py -v`
Expected: FAIL — `module 'labjury' has no attribute '__version__'` (and the core-names test fails since `__version__` isn't in `__all__` yet).

- [ ] **Step 3: Add `__version__` to `src/labjury/__init__.py`**

Add `__version__ = "0.0.1"` near the top (before imports is fine). Append `"__version__"` to `__all__` (a `# meta` group).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_version.py tests/test_public_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_version.py tests/test_public_api.py
git commit -m "feat: labjury.__version__ synced to pyproject; __all__ as the SemVer contract"
```

---

### Task 2: `assert_plugin_conforms` stage-plugin conformance checker

**Files:**
- Modify: `src/labjury/testing.py` (add `assert_plugin_conforms` + the maps)
- Test: `tests/test_testing_helpers.py` (new) — or append to an existing testing-helpers test if present

**Interfaces:**
- Consumes: the plugin protocols from `labjury.plugins`; `inspect`.
- Produces: `labjury.testing.assert_plugin_conforms(obj: object, protocol: type) -> None` — asserts `isinstance(obj, protocol)`; every async method named for that protocol is a coroutine function on `obj`; every capability attr named for that protocol is a `frozenset`. Raises `AssertionError` with a message naming the protocol/attr on first violation.

- [ ] **Step 1: Write the failing tests** in `tests/test_testing_helpers.py`

```python
import pytest

from labjury.plugins import Scorer
from labjury.testing import assert_plugin_conforms


class _GoodScorer:
    accepts = frozenset({"text"})
    async def score(self, state, questions):
        return []


class _SyncScorer:
    accepts = frozenset({"text"})
    def score(self, state, questions):   # not async
        return []


class _BadAccepts:
    accepts = {"text"}                    # set, not frozenset
    async def score(self, state, questions):
        return []


class _NoScore:
    accepts = frozenset({"text"})         # missing score


def test_conforms_passes_good_scorer():
    assert_plugin_conforms(_GoodScorer(), Scorer)   # no raise


def test_conforms_rejects_sync_method():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_SyncScorer(), Scorer)


def test_conforms_rejects_non_frozenset_accepts():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_BadAccepts(), Scorer)


def test_conforms_rejects_missing_method():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_NoScore(), Scorer)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_testing_helpers.py -v`
Expected: FAIL — `cannot import name 'assert_plugin_conforms'`.

- [ ] **Step 3: Implement `assert_plugin_conforms` in `src/labjury/testing.py`**

Import the protocols (`ContextBuilder`, `Proposer`, `Scorer`, `DecisionPolicy`, `Sink`, `Cache`, `TaxonomyStore`, `AuditLog`, `RubricStore`, `Redactor`, `Guard`, `ReviewQueue`) and `inspect`. Define `_ASYNC_METHODS: dict[type, tuple[str, ...]]` and `_CAPABILITY_ATTRS: dict[type, tuple[str, ...]]` per the current protocol definitions. `assert_plugin_conforms(obj, protocol)`: `assert isinstance(obj, protocol)`; for each name in `_ASYNC_METHODS.get(protocol, ())` assert `inspect.iscoroutinefunction(getattr(obj, name))`; for each attr in `_CAPABILITY_ATTRS.get(protocol, ())` assert `isinstance(getattr(obj, attr), frozenset)`. Clear messages.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_testing_helpers.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/testing.py tests/test_testing_helpers.py
git commit -m "feat: assert_plugin_conforms — stage-plugin structural conformance checker"
```

---

### Task 3: Public surface + versioning doc

**Files:**
- Modify: `src/labjury/__init__.py` (export `assert_plugin_conforms`)
- Modify: `tests/test_public_api.py` (add to the curated set if load-bearing — optional)
- Create: `docs/versioning.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `assert_plugin_conforms` (Task 2, from `labjury.testing`).
- Produces: `labjury.assert_plugin_conforms` importable.

- [ ] **Step 1: Write the failing test**

Append `"assert_plugin_conforms"` to the list the suite checks — add it to `_MUST_REMAIN_PUBLIC` in `tests/test_public_api.py` (so the core-names test now also requires it to be exported).

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_public_api.py::test_core_names_remain_public -v`
Expected: FAIL — `core public names dropped from __all__: {'assert_plugin_conforms'}`.

- [ ] **Step 3: Re-export in `src/labjury/__init__.py`**

Add `assert_plugin_conforms` to the `from labjury.testing import (...)` block and to `__all__` under the testing-helpers group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 5: Write `docs/versioning.md` and link it**

`docs/versioning.md`: LabJury's SemVer policy — `labjury.__version__`; the public surface is exactly `labjury.__all__` (anything not exported is internal and may change any time); what a major/minor/patch bump means; the plugin-contract stability promise (the `@runtime_checkable` protocols and their signatures are the contract; additive optional fields are minor, signature changes are major); how to prove a plugin conforms — `assert_plugin_conforms` for stage plugins and the stateful-backend suites (`assert_taxonomy_store_contract`, `assert_audit_log_contract`, `assert_rubric_store_contract`) for backends; and that behavioral correctness of a scorer/policy is the author's, not universally assertable. Add "### Versioning & plugin conformance" to `README.md` and "### Phiên bản & kiểm chuẩn plugin" to `README.vi.md` after the evaluation section, each linking the doc.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/versioning.md README.md README.vi.md
git commit -m "feat: export assert_plugin_conforms; versioning & conformance policy doc"
```
