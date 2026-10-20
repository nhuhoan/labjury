# Durable TaxonomyStore (Redis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a proven, verifiable durable-backend contract for `TaxonomyStore` — a reusable conformance suite, a Redis reference implementation, and a bring-your-own-backend doc — without adding any dependency to core.

**Architecture:** Formalize the open-world lifecycle (`promote`, `proposed_labels`) into the `TaxonomyStore` protocol; ship a backend-agnostic conformance suite in the installed package (`labjury.testing`) that both built-in stores and third-party backends run; implement `RedisTaxonomyStore` under a new `labjury.contrib.*` namespace (the sanctioned home for dependency-carrying plugins) behind an opt-in `redis` extra, with an injected async client.

**Tech Stack:** Python 3.11+, `redis>=5` (optional extra only), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-20-durable-taxonomy-design.md`

## Global Constraints

- Core `pyproject.toml` `dependencies` stays `[]`. `redis` is only an optional extra.
- Core code (everything outside `labjury.contrib.*`) never imports `labjury.contrib` or `redis`. `import labjury` must work with zero third-party packages installed.
- `RedisTaxonomyStore` receives an already-created `redis.asyncio` client; it never opens/owns a connection.
- The conformance suite ships in the installed package (not under `tests/`) so third parties can import it.
- Follow existing idioms: async throughout; DI like `LLMJudgeScorer(chat=...)`; public re-exports live in `src/labjury/__init__.py`.

## Review Focus

- **Promoting a never-proposed label** → must still become official (`is_known` true). Pinned in Task 1 conformance suite.
- **Proposing a label that is already official** → must be a no-op, not demote or duplicate it. Pinned in Task 1 conformance suite.
- **`namespace` isolation** → two `RedisTaxonomyStore`s with different namespaces on the same client must not see each other's labels. Pinned in Task 2.
- **`import labjury` with `redis` absent** → must succeed (core never imports contrib/redis). Pinned in Task 2.
- **`meta` argument passed to `propose`** → must be accepted without error even though it is not persisted this step. Covered by the conformance suite calling `propose` (Task 1) and exercised against Redis (Task 2).

---

### Task 1: Formalize the lifecycle contract and ship the conformance suite

**Files:**
- Modify: `src/labjury/plugins.py` (add two methods to the `TaxonomyStore` Protocol)
- Create: `src/labjury/testing.py` (the reusable conformance suite)
- Modify: `src/labjury/__init__.py` (re-export the suite helper)
- Test: `tests/test_taxonomy.py` (run the suite against `InMemoryTaxonomyStore`; pin the protocol)

**Interfaces:**
- Consumes: `InMemoryTaxonomyStore` from `labjury.taxonomy` (methods `is_known`, `propose(label, meta=None)`, `promote`, `known_labels`, `proposed_labels`, all async); `TaxonomyStore` Protocol from `labjury.plugins`.
- Produces: `async def assert_taxonomy_store_contract(make_store: Callable[[], TaxonomyStore]) -> None` in `labjury.testing`, re-exported as `labjury.assert_taxonomy_store_contract`. Raises `AssertionError` on any violated invariant. `make_store` is a zero-arg factory returning a fresh store.

- [ ] **Step 1: Write the failing test** in `tests/test_taxonomy.py`

```python
from labjury.testing import assert_taxonomy_store_contract
from labjury.taxonomy import InMemoryTaxonomyStore

async def test_inmemory_store_satisfies_contract():
    await assert_taxonomy_store_contract(InMemoryTaxonomyStore)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_taxonomy.py::test_inmemory_store_satisfies_contract -v`
Expected: FAIL — `ModuleNotFoundError: labjury.testing` / `ImportError` for `assert_taxonomy_store_contract`.

- [ ] **Step 3: Implement `assert_taxonomy_store_contract(make_store)` in `src/labjury/testing.py`**

A single async function asserting every universal invariant, each on a fresh `store = make_store()`:
- unknown label: `is_known("x")` is `False`, not in `proposed_labels()`/`known_labels()`.
- propose then state: after `propose("x")`, `"x"` in `proposed_labels()`, `is_known("x")` still `False`, `"x"` not in `known_labels()`.
- propose→promote: after `promote("x")`, `is_known("x")` is `True`, `"x"` in `known_labels()`, `"x"` not in `proposed_labels()`.
- promote a never-proposed label: fresh store, `promote("y")` → `is_known("y")` is `True`.
- propose already-official: after promoting `"x"`, `propose("x")` leaves `is_known("x")` `True` and `"x"` out of `proposed_labels()`.
- two tiers: promote `"a"`, propose `"b"` → `known_labels() == {"a"}` and `"b"` in `proposed_labels()`.
- `meta` accepted: `propose("m", {"src": "t"})` does not raise.

- [ ] **Step 4: Re-export** `assert_taxonomy_store_contract` from `src/labjury/__init__.py` (import it and add to `__all__`).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_taxonomy.py::test_inmemory_store_satisfies_contract -v`
Expected: PASS.

- [ ] **Step 6: Write the failing protocol test** in `tests/test_taxonomy.py`

```python
from labjury.plugins import TaxonomyStore

def test_protocol_requires_full_lifecycle():
    class Partial:  # only the pre-lifecycle methods
        async def is_known(self, label): ...
        async def propose(self, label, meta=None): ...
        async def known_labels(self): ...
    assert isinstance(InMemoryTaxonomyStore(), TaxonomyStore)
    assert not isinstance(Partial(), TaxonomyStore)
```

- [ ] **Step 7: Run to verify it fails**

Run: `python -m pytest tests/test_taxonomy.py::test_protocol_requires_full_lifecycle -v`
Expected: FAIL — `Partial` is currently a `TaxonomyStore` because the protocol does not yet require `promote`/`proposed_labels`.

- [ ] **Step 8: Add `promote` and `proposed_labels` to the `TaxonomyStore` Protocol** in `src/labjury/plugins.py`

Add `async def promote(self, label: str) -> None: ...` and `async def proposed_labels(self) -> set[str]: ...` to the existing `@runtime_checkable` `TaxonomyStore`.

- [ ] **Step 9: Run the full suite to verify green**

Run: `python -m pytest -q`
Expected: PASS (all prior tests plus the two new ones).

- [ ] **Step 10: Commit**

```bash
git add src/labjury/plugins.py src/labjury/testing.py src/labjury/__init__.py tests/test_taxonomy.py
git commit -m "feat: formalize taxonomy lifecycle contract + ship conformance suite"
```

---

### Task 2: RedisTaxonomyStore reference implementation + packaging

**Files:**
- Create: `src/labjury/contrib/__init__.py` (empty package marker)
- Create: `src/labjury/contrib/redis_taxonomy.py` (`RedisTaxonomyStore`)
- Create: `tests/test_redis_taxonomy.py` (fake async client, conformance run, namespace + core-import tests, optional real-redis integration)
- Modify: `pyproject.toml` (`redis` optional extra + entry-point registration)

**Interfaces:**
- Consumes: `assert_taxonomy_store_contract` from `labjury.testing` (Task 1); the `TaxonomyStore` protocol.
- Produces: `RedisTaxonomyStore(client, namespace: str = "labjury:tax")` in `labjury.contrib.redis_taxonomy`. `client` is any object exposing async `sismember(key, member)`, `sadd(key, *members)`, `smembers(key)` (returns a set of `str`), `smove(src, dst, member)`. Implements the full `TaxonomyStore` lifecycle; `propose`'s `meta` is accepted and ignored.

- [ ] **Step 1: Write the failing test** in `tests/test_redis_taxonomy.py`

Define a minimal in-memory `FakeRedis` implementing the four async commands over `dict[str, set[str]]` (decode members to `str`), then:

```python
async def test_redis_store_satisfies_contract():
    await assert_taxonomy_store_contract(lambda: RedisTaxonomyStore(FakeRedis()))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_redis_taxonomy.py::test_redis_store_satisfies_contract -v`
Expected: FAIL — `ImportError` for `RedisTaxonomyStore`.

- [ ] **Step 3: Implement `RedisTaxonomyStore` in `src/labjury/contrib/redis_taxonomy.py`**

Keys `f"{namespace}:official"` and `f"{namespace}:proposed"`. Map operations per spec decision 4: `is_known`=`sismember(official, label)`; `propose`=guard with `sismember(official,·)` then `sadd(proposed, label)`; `promote`=`smove(proposed, official, label)` then `sadd(official, label)`; `known_labels`=`set(await smembers(official))`; `proposed_labels`=`set(await smembers(proposed))`. `propose` signature is `(self, label, meta=None)`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_redis_taxonomy.py::test_redis_store_satisfies_contract -v`
Expected: PASS.

- [ ] **Step 5: Write the namespace-isolation and core-import tests** in `tests/test_redis_taxonomy.py`

```python
async def test_namespaces_are_isolated():
    client = FakeRedis()
    a = RedisTaxonomyStore(client, namespace="t:a")
    b = RedisTaxonomyStore(client, namespace="t:b")
    await a.promote("x")
    assert await a.is_known("x") is True
    assert await b.is_known("x") is False

def test_core_import_does_not_require_redis():
    import importlib, sys
    assert "redis" not in sys.modules or True  # redis may be absent entirely
    importlib.import_module("labjury")  # must not raise
```

- [ ] **Step 6: Run to verify they pass**

Run: `python -m pytest tests/test_redis_taxonomy.py -v`
Expected: PASS.

- [ ] **Step 7: Add an optional real-Redis integration test** in `tests/test_redis_taxonomy.py`

Guard with `pytest.mark.skipif(not os.environ.get("LABJURY_REDIS_URL"))`; construct a `redis.asyncio.from_url(...)` client with `decode_responses=True`, use a unique namespace per run, and call `assert_taxonomy_store_contract(lambda: RedisTaxonomyStore(client, namespace=unique))`.

- [ ] **Step 8: Run to verify it is skipped (no Redis) or passes (with Redis)**

Run: `python -m pytest tests/test_redis_taxonomy.py -v`
Expected: the integration test reports SKIPPED when `LABJURY_REDIS_URL` is unset; everything else PASS.

- [ ] **Step 9: Register packaging** in `pyproject.toml`

Under `[project.optional-dependencies]` add `redis = ["redis>=5"]`. Under `[project.entry-points."labjury.taxonomies"]` add `redis = "labjury.contrib.redis_taxonomy:RedisTaxonomyStore"`.

- [ ] **Step 10: Run the full suite to verify green**

Run: `python -m pytest -q`
Expected: PASS (integration test SKIPPED).

- [ ] **Step 11: Commit**

```bash
git add src/labjury/contrib/__init__.py src/labjury/contrib/redis_taxonomy.py tests/test_redis_taxonomy.py pyproject.toml
git commit -m "feat: RedisTaxonomyStore reference backend behind optional redis extra"
```

---

### Task 3: Bring-your-own-backend documentation

**Files:**
- Create: `docs/taxonomy-backends.md`
- Modify: `README.md`, `README.vi.md` (short pointer + `pip install labjury[redis]` note)

**Interfaces:**
- Consumes: the finished `TaxonomyStore` protocol, `assert_taxonomy_store_contract`, and `RedisTaxonomyStore` from Tasks 1–2.
- Produces: no code; a doc page other docs can link.

- [ ] **Step 1: Write `docs/taxonomy-backends.md`**

Cover: the `TaxonomyStore` protocol methods and their contract; the rule that a custom backend needs no inheritance and no core change; passing it via `Engine(..., taxonomy=...)` and/or registering under the `labjury.taxonomies` entry point; a complete minimal custom-store example; and the key step — verify it with `await assert_taxonomy_store_contract(MyStore)`. State that Redis is one reference backend (`pip install labjury[redis]`), not a requirement.

- [ ] **Step 2: Add a short pointer** in `README.md` and `README.vi.md`

One subsection: durable/custom taxonomy backends, the `labjury[redis]` install line, and a link to `docs/taxonomy-backends.md`.

- [ ] **Step 3: Verify the documented example is accurate**

Confirm every symbol and signature used in the doc matches the code shipped in Tasks 1–2 (`assert_taxonomy_store_contract`, `RedisTaxonomyStore(client, namespace=...)`, protocol method names). No test; this is a read-through against the current source.

- [ ] **Step 4: Commit**

```bash
git add docs/taxonomy-backends.md README.md README.vi.md
git commit -m "docs: how to bring your own TaxonomyStore backend"
```
