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

from typing import Awaitable, Callable, Union

from labjury.plugins import TaxonomyStore

StoreFactory = Callable[[], Union[TaxonomyStore, Awaitable[TaxonomyStore]]]


async def _make(factory: StoreFactory) -> TaxonomyStore:
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
