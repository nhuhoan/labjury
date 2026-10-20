"""Reusable conformance suite for :class:`~labjury.plugins.TaxonomyStore`.

Shipped in the installed package (not under ``tests/``) so a third party
building their own taxonomy backend can import it and prove drop-in
equivalence::

    from labjury.testing import assert_taxonomy_store_contract
    await assert_taxonomy_store_contract(MyTaxonomyStore)

The suite asserts only the *universal* open-world invariants every backend
must honor; backend-specific behavior (e.g. whether ``meta`` is persisted) is
not part of it.
"""

from __future__ import annotations

import inspect
from typing import Awaitable, Callable, Union

from labjury.audit import AuditEvent
from labjury.decisions import NoulQuestion
from labjury.plugins import (
    AuditLog,
    Cache,
    ContextBuilder,
    DecisionPolicy,
    Guard,
    Proposer,
    Redactor,
    ReviewQueue,
    RubricStore,
    Scorer,
    Sink,
    TaxonomyStore,
)

StoreFactory = Callable[[], Union[TaxonomyStore, Awaitable[TaxonomyStore]]]
AuditLogFactory = Callable[[], AuditLog]
RubricStoreFactory = Callable[[], Union[RubricStore, Awaitable[RubricStore]]]


async def _make(factory: StoreFactory) -> TaxonomyStore:
    store = factory()
    if hasattr(store, "__await__"):
        store = await store  # type: ignore[assignment]
    return store  # type: ignore[return-value]


async def _make_rubric_store(factory: RubricStoreFactory) -> RubricStore:
    store = factory()
    if hasattr(store, "__await__"):
        store = await store  # type: ignore[assignment]
    return store  # type: ignore[return-value]


async def assert_taxonomy_store_contract(make_store: StoreFactory) -> None:
    """Drive a fresh store from ``make_store`` through every invariant.

    ``make_store`` is a zero-argument factory returning a fresh store (sync or
    async). Raises :class:`AssertionError` on the first violated invariant.
    """

    # Unknown label: absent from every tier.
    store = await _make(make_store)
    assert await store.is_known("x") is False
    assert "x" not in await store.proposed_labels()
    assert "x" not in await store.known_labels()

    # propose: enters the proposed tier, not yet known.
    store = await _make(make_store)
    await store.propose("x")
    assert "x" in await store.proposed_labels()
    assert await store.is_known("x") is False
    assert "x" not in await store.known_labels()

    # propose -> promote: becomes known, leaves the proposed tier.
    store = await _make(make_store)
    await store.propose("x")
    await store.promote("x")
    assert await store.is_known("x") is True
    assert "x" in await store.known_labels()
    assert "x" not in await store.proposed_labels()

    # promote a never-proposed label: still becomes known.
    store = await _make(make_store)
    await store.promote("y")
    assert await store.is_known("y") is True
    assert "y" in await store.known_labels()

    # propose an already-official label: no-op (stays known, not re-proposed).
    store = await _make(make_store)
    await store.promote("x")
    await store.propose("x")
    assert await store.is_known("x") is True
    assert "x" not in await store.proposed_labels()

    # two tiers coexist independently.
    store = await _make(make_store)
    await store.promote("a")
    await store.propose("b")
    assert await store.known_labels() == {"a"}
    assert "b" in await store.proposed_labels()

    # meta is accepted (not necessarily persisted).
    store = await _make(make_store)
    await store.propose("m", {"src": "test"})
    assert "m" in await store.proposed_labels()


async def assert_audit_log_contract(make_log: AuditLogFactory) -> None:
    """Drive a fresh audit log from ``make_log`` through the append-only contract.

    Raises :class:`AssertionError` on any violation. ``NullAuditLog`` is the
    opt-out and is exempt (it retains nothing by design).
    """
    log = make_log()

    # append-only: no mutation surface.
    assert not hasattr(type(log), "update")
    assert not hasattr(type(log), "delete")

    # empty for an unknown id.
    assert await log.by_correlation("missing") == []

    # records are retrievable per correlation id, in insertion order.
    e1 = AuditEvent("a", "fp-a-1")
    e2 = AuditEvent("a", "fp-a-2")
    e3 = AuditEvent("b", "fp-b-1")
    await log.record(e1)
    await log.record(e3)
    await log.record(e2)
    assert await log.by_correlation("a") == [e1, e2]
    assert await log.by_correlation("b") == [e3]
    assert await log.by_correlation("missing") == []


async def assert_rubric_store_contract(make_store: RubricStoreFactory) -> None:
    """Drive a fresh :class:`~labjury.plugins.RubricStore` through every invariant.

    ``make_store`` is a zero-argument factory returning a fresh store (sync or
    async). Raises :class:`AssertionError` on the first violated invariant. The
    suite asserts only the universal invariants every backend must honor.
    """

    # Unregistered label: empty on every read, never KeyError.
    store = await _make_rubric_store(make_store)
    assert await store.resolve("x") is None
    assert await store.get("x", "v1") is None
    assert await store.history("x") == []

    # register -> resolve returns it; history lists the one version.
    store = await _make_rubric_store(make_store)
    q1 = NoulQuestion("x", "first?")
    r = await store.register("x", q1, "v1")
    assert r.label == "x" and r.question == q1 and r.version == "v1"
    assert await store.resolve("x") == r
    assert await store.history("x") == ["v1"]

    # two versions: resolve is the latest, get(old) survives, history is ordered.
    store = await _make_rubric_store(make_store)
    await store.register("x", NoulQuestion("x", "old?"), "v1")
    await store.register("x", NoulQuestion("x", "new?"), "v2")
    assert (await store.resolve("x")).version == "v2"
    assert (await store.get("x", "v1")).question == NoulQuestion("x", "old?")
    assert await store.history("x") == ["v1", "v2"]

    # a published version is immutable: re-publishing with a different question errors.
    store = await _make_rubric_store(make_store)
    await store.register("x", NoulQuestion("x", "first?"), "v1")
    try:
        await store.register("x", NoulQuestion("x", "changed?"), "v1")
    except ValueError:
        pass
    else:
        raise AssertionError("re-publishing a version with a different question must raise")


# -- stage-plugin structural conformance -------------------------------------

# Each plugin protocol's async methods and capability attributes. These are what
# a bare ``isinstance`` against a @runtime_checkable protocol does NOT verify
# (it checks member *presence*, not that a method is async or an attr is typed).
_ASYNC_METHODS: dict[type, tuple[str, ...]] = {
    ContextBuilder: ("build",),
    Proposer: ("propose",),
    Scorer: ("score",),
    DecisionPolicy: ("decide",),
    Sink: ("emit",),
    Cache: ("get", "put"),
    TaxonomyStore: ("is_known", "propose", "promote", "known_labels", "proposed_labels"),
    AuditLog: ("record", "by_correlation"),
    RubricStore: ("register", "resolve", "get", "history"),
    Redactor: ("redact",),
    Guard: ("inspect",),
    ReviewQueue: ("enqueue",),
}

_CAPABILITY_ATTRS: dict[type, tuple[str, ...]] = {
    ContextBuilder: ("accepts", "produces"),
    Proposer: ("accepts",),
    Scorer: ("accepts",),
    Redactor: ("accepts",),
}


def assert_plugin_conforms(obj: object, protocol: type) -> None:
    """Assert that ``obj`` is a valid LabJury plugin for ``protocol``.

    Adds exactly what a bare ``isinstance`` against the ``@runtime_checkable``
    protocol misses: that every async method the protocol defines is an actual
    coroutine function, and that declared capability attributes (``accepts`` /
    ``produces``) are ``frozenset``s. Structural member *presence* is covered by
    the ``isinstance`` check itself. Raises :class:`AssertionError` on the first
    violation. Behavioral correctness (does a scorer score *well*?) is
    domain-specific and not checked here.
    """
    assert isinstance(obj, protocol), (
        f"{type(obj).__name__} is not a structural {protocol.__name__} "
        "(a required member is missing)"
    )
    for name in _ASYNC_METHODS.get(protocol, ()):
        method = getattr(obj, name)
        assert inspect.iscoroutinefunction(method), (
            f"{protocol.__name__}.{name} must be an async method on "
            f"{type(obj).__name__}"
        )
    for attr in _CAPABILITY_ATTRS.get(protocol, ()):
        value = getattr(obj, attr)
        assert isinstance(value, frozenset), (
            f"{protocol.__name__}.{attr} must be a frozenset on "
            f"{type(obj).__name__}, got {type(value).__name__}"
        )
