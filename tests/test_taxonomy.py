from labjury.taxonomy import InMemoryTaxonomyStore


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
