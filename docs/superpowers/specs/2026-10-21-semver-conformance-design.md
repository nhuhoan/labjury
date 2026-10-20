# SemVer + plugin conformance — a versioned, self-guarding public contract

**Status:** design (CTO-decided; owner delegated design authority, "ok" 2026-10-21) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Enterprise readiness **Tier 3** (ecosystem), **item 2 of 3** — SemVer + plugin conformance suite. First Tier-3 slice (chosen before the gRPC service: you version and conformance-test the contract before building an ecosystem on it). Builds on the existing in-package conformance suites and the `__all__` public surface.

## Intent and the why

Tier 1 and Tier 2 are done; the public surface is large and stable enough that
external teams will want to build on it — write plugins, pin a dependency range,
trust that an upgrade won't silently break them. That trust needs two things the
project does not yet declare:

1. **A version and a compatibility policy.** There is a `version` in `pyproject.toml`
   (`0.0.1`) but no `labjury.__version__`, and nothing states what counts as a
   breaking change. An ecosystem needs SemVer with a named public surface.
2. **A way for a plugin author to prove conformance.** The stateful backends have
   in-package suites (`assert_taxonomy_store_contract`, `assert_audit_log_contract`,
   `assert_rubric_store_contract`), but the *stage* plugins (Scorer, Proposer,
   ContextBuilder, DecisionPolicy, Sink, Cache, Observer) have no single "is my
   plugin wired correctly?" check beyond a bare `isinstance`.

LabJury owns the **policy and the checker**, not anyone's release process. It
declares what is public and what SemVer means for it, and ships a conformance helper;
it does not run a deployer's CI or publish on their behalf.

## Goals

- **`labjury.__version__`** — a single string constant on the package, equal to the
  `pyproject.toml` `[project].version`. A test parses `pyproject.toml` with `tomllib`
  (stdlib) and asserts the two match, so they never drift. Added to `__all__`.
- **Self-guarding public surface** (SemVer contract made executable):
  - `test_public_surface_importable` iterates `labjury.__all__` and asserts every name
    resolves on the package — so `__all__` *is* the enforced contract.
  - A curated "must remain public" set is asserted to be a subset of `__all__` — a
    guard against silently dropping a load-bearing export (which would be a major bump).
  - `test_exported_protocols_are_runtime_checkable` asserts every exported plugin
    Protocol is `@runtime_checkable` (sets `_is_runtime_protocol`), so external authors
    can `isinstance`-check their implementations.
- **`assert_plugin_conforms(obj, protocol)`** in `labjury.testing` — the stage-plugin
  conformance checker. Adds exactly what a bare `isinstance` against a
  `@runtime_checkable` protocol misses:
  - `isinstance(obj, protocol)` (structural member presence) — the headline check,
    with a clear `AssertionError` naming the protocol when it fails;
  - every async method the protocol defines is an actual coroutine function on `obj`
    (`isinstance` only checks the attribute exists, not that it is `async`);
  - declared capability attributes (`accepts`, `produces`) are `frozenset`s
    (`isinstance` checks presence, not type).
- **Docs:** `docs/versioning.md` — the SemVer/compatibility policy (public surface,
  what breaks, the plugin-contract stability promise, the conformance suites) + a
  bilingual README pointer.

## Non-goals / anti-goals

- **No broad governance docs** (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT) — that is
  Tier 3 item 3, a separate slice.
- **No release automation / no auto-bump / no CHANGELOG generator.** Version is a
  hand-set constant; the test only guards that the two places agree.
- **No behavioral conformance for stage plugins beyond structure.** Whether a Scorer
  scores *correctly* is domain-specific and not universally assertable; the helper
  checks the contract shape (async, capability types, membership), and the doc says so.
  Behavioral conformance for the stateful backends stays in their existing suites.
- **No change to any plugin contract, protocol, or public signature.** This slice
  only *adds* `__version__`, a conformance helper, tests, and a doc.
- **No new dependency.** `tomllib` is stdlib (3.11+); everything else is pure Python.

## Constraints (inherited)

- Core `dependencies = []`; stdlib only; conformance helper in `labjury.testing`
  (ships in-package, like the other suites). Core never imports `labjury.contrib`.
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### `__version__` (`labjury/__init__.py`)

A module constant `__version__ = "0.0.1"` near the top, exported in `__all__`. The
sync test (`tests/test_version.py`) reads `pyproject.toml` via `tomllib` from the repo
root (resolved relative to the test file) and asserts equality.

### `assert_plugin_conforms` (`labjury/testing.py`)

```python
def assert_plugin_conforms(obj: object, protocol: type) -> None: ...
```

Driven by two small internal maps keyed by protocol (stable — a handful of
protocols): `_ASYNC_METHODS` (protocol → the method names that must be coroutine
functions) and `_CAPABILITY_ATTRS` (protocol → attrs that must be `frozenset`). The
function asserts `isinstance`, then the async-ness of each listed method via
`inspect.iscoroutinefunction`, then the frozenset type of each capability attr.

### Public-surface guard (`tests/test_public_api.py`)

Replace the hard-coded hasattr loop with: (1) iterate `lj.__all__` for importability;
(2) assert a curated `_MUST_REMAIN_PUBLIC` set ⊆ `lj.__all__`; (3) a new test asserting
the exported protocols carry `_is_runtime_protocol`.

## What's left to the builder

- The exact membership of `_MUST_REMAIN_PUBLIC` (the load-bearing names: `Engine`,
  `Item`, `State`, the stage protocols, the registry functions) — the builder lists
  the obviously-core ones; it is a guard, not an exhaustive mirror of `__all__`.
- The `_ASYNC_METHODS` / `_CAPABILITY_ATTRS` maps follow the current protocol
  definitions in `labjury.plugins`.

## Review focus (inputs the tests must pin)

- **`labjury.__version__` equals `pyproject` version** — Task 1.
- **Every `__all__` name is importable**; a curated core set is a subset of `__all__`
  — Task 1.
- **Exported stage protocols are `@runtime_checkable`** (`isinstance` works) — Task 1.
- **`assert_plugin_conforms` passes a correct plugin** and **fails a non-async method**,
  a **wrong-typed `accepts`** (`set`/`list` not `frozenset`), and a **structurally
  missing method** — Task 2.
