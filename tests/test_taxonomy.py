from labjury.plugins import TaxonomyStore
from labjury.taxonomy import InMemoryTaxonomyStore
from labjury.testing import assert_taxonomy_store_contract


async def test_inmemory_store_satisfies_contract():
    await assert_taxonomy_store_contract(InMemoryTaxonomyStore)


def test_protocol_requires_full_lifecycle():
    class Partial:  # only the pre-lifecycle methods
        async def is_known(self, label): ...
        async def propose(self, label, meta=None): ...
        async def known_labels(self): ...

    assert isinstance(InMemoryTaxonomyStore(), TaxonomyStore)
    assert not isinstance(Partial(), TaxonomyStore)


async def test_taxonomy_open_world_lifecycle():
    tax = InMemoryTaxonomyStore()
    assert await tax.is_known("asmr") is False
    await tax.propose("asmr")
    assert "asmr" in await tax.proposed_labels() and await tax.is_known("asmr") is False
    await tax.promote("asmr")
    assert await tax.is_known("asmr") is True


async def test_known_labels_reflects_promoted_only():
    tax = InMemoryTaxonomyStore()
    await tax.propose("food")
    await tax.promote("food")
    await tax.propose("mukbang")  # proposed, not promoted
    assert await tax.known_labels() == {"food"}
