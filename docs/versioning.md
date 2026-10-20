# Versioning & plugin conformance

LabJury follows [Semantic Versioning](https://semver.org). This page states exactly
what that promise covers, so you can depend on a version range and know what an
upgrade may and may not change.

## The version

`labjury.__version__` is the single source of truth and always equals the version in
`pyproject.toml` (a test enforces that they never drift).

## The public surface is `labjury.__all__`

**Everything exported from the top-level `labjury` package (i.e. listed in
`labjury.__all__`) is public API.** Anything not exported there — submodule paths,
underscore-prefixed names, internal helpers — is internal and may change in any
release without notice.

Under SemVer, given a version `MAJOR.MINOR.PATCH`:

- **MAJOR** — a breaking change to the public surface: removing or renaming an
  exported name, changing a public function/method signature incompatibly, changing
  a plugin protocol's methods, or tightening behavior a reasonable caller relied on.
- **MINOR** — backward-compatible additions: a new exported name, a new **optional,
  defaulted** field on a value object (as `Candidate.rubric_version`, `tenant`, and
  `ItemResult.latency_ms` were added), a new plugin kind.
- **PATCH** — backward-compatible bug fixes.

A test (`test_core_names_remain_public`) guards the load-bearing names against an
accidental drop; `test_public_surface_importable` guarantees every `__all__` name
resolves.

> Pre-1.0 note: while the version is `0.x`, the surface may still move as the design
> settles. The policy above is how it will behave; `1.0.0` is the point at which the
> MAJOR promise becomes binding.

## The plugin contract

Plugins are duck-typed against the `@runtime_checkable` protocols in `labjury.plugins`
(re-exported at top level): `ContextBuilder`, `Proposer`, `Scorer`, `DecisionPolicy`,
`Sink`, `Cache`, `Observer`, `TaxonomyStore`, `AuditLog`, `RubricStore`, `Redactor`,
`Guard`, `ReviewQueue`. Those protocols — their method names, signatures, and
capability attributes (`accepts`/`produces`) — are the contract. They are
`@runtime_checkable`, so you can `isinstance`-check your implementation.

### Proving conformance

- **Stage plugins** (ContextBuilder, Proposer, Scorer, DecisionPolicy, Sink, Cache,
  Observer, and the wrapper-seam protocols Redactor/Guard/ReviewQueue):

  ```python
  from labjury.testing import assert_plugin_conforms
  from labjury.plugins import Scorer

  assert_plugin_conforms(my_scorer, Scorer)
  ```

  This checks what a bare `isinstance` cannot: that every async method really is a
  coroutine function, and that capability attributes are `frozenset`s. It does **not**
  judge behavioral correctness — whether your scorer scores *well* is domain-specific
  and yours to test.

- **Stateful backends** have behavioral conformance suites that drive a fresh instance
  through every universal invariant:

  ```python
  from labjury.testing import (
      assert_taxonomy_store_contract,
      assert_audit_log_contract,
      assert_rubric_store_contract,
  )

  await assert_taxonomy_store_contract(MyTaxonomyStore)   # zero-arg factory
  ```

All of these ship inside the installed package (`labjury.testing`) so you can run them
in your own test suite against your own backends.
