from labjury.results import Action, ItemResult, Status, Verdict
from labjury.service.handler import DecisionHandler


class _FakeEngine:
    def __init__(self, by_id):
        self._by_id = by_id

    async def process(self, item):
        return self._by_id[item.id]

    async def process_batch(self, items):
        return [self._by_id[i.id] for i in items]


def _decided(cid, labels):
    return ItemResult(
        cid, Status.DECIDED, verdict=Verdict(Action.ACCEPT, labels, {}, [], "ok")
    )


async def test_handler_decide():
    eng = _FakeEngine({"i1": _decided("i1", ["spam"])})
    w = await DecisionHandler(eng).decide("i1", {"text": "x"}, "acme")
    assert w["correlation_id"] == "i1"
    assert w["status"] == "STATUS_DECIDED"
    assert w["verdict"]["labels"] == ["spam"]


async def test_handler_decide_failed():
    eng = _FakeEngine({"i1": ItemResult("i1", Status.FAILED, error="boom")})
    w = await DecisionHandler(eng).decide("i1", {}, None)
    assert w["verdict"] is None and w["error"] == "boom"


async def test_handler_decide_batch():
    eng = _FakeEngine({"i1": _decided("i1", ["a"]), "i2": _decided("i2", ["b"])})
    out = await DecisionHandler(eng).decide_batch([("i1", {}, None), ("i2", {}, "t")])
    assert [w["correlation_id"] for w in out] == ["i1", "i2"]
    assert out[1]["verdict"]["labels"] == ["b"]
