from labjury import Action, ItemResult, Status, Verdict
from labjury.defaults import CollectingSink, InMemoryCache


async def test_cache_round_trip():
    c = InMemoryCache()
    assert await c.get("h1") is None
    v = Verdict(Action.ACCEPT, ["food"], {"food": 0.9}, [], "ok")
    await c.put("h1", v)
    assert (await c.get("h1")).labels == ["food"]


async def test_sink_collects():
    s = CollectingSink()
    await s.emit(ItemResult("i1", Status.DECIDED))
    assert s.results[0].correlation_id == "i1"
