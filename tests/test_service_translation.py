from labjury.results import Action, ItemResult, Status, Verdict
from labjury.service.translation import item_from_wire, result_to_wire


def test_item_from_wire():
    item = item_from_wire("i1", {"text": "x"}, "acme")
    assert item.id == "i1" and item.raw == {"text": "x"} and item.tenant == "acme"


def test_empty_tenant_is_none():
    assert item_from_wire("i1", {}, "").tenant is None


def test_result_to_wire_decided():
    v = Verdict(Action.BLOCK, ["nsfw"], {"nsfw": 0.9}, ["novel"], "bad")
    r = ItemResult("i1", Status.DECIDED, verdict=v, latency_ms=12.5, tenant="acme")
    w = result_to_wire(r)
    assert w["correlation_id"] == "i1"
    assert w["status"] == "STATUS_DECIDED"
    assert w["verdict"]["action"] == "ACTION_BLOCK"
    assert w["verdict"]["labels"] == ["nsfw"]
    assert w["verdict"]["scores"] == {"nsfw": 0.9}
    assert w["verdict"]["novel_labels"] == ["novel"]
    assert w["verdict"]["reason"] == "bad"
    assert w["latency_ms"] == 12.5 and w["tenant"] == "acme"


def test_result_to_wire_failed():
    r = ItemResult("i1", Status.FAILED, error="boom")
    w = result_to_wire(r)
    assert w["status"] == "STATUS_FAILED"
    assert w["verdict"] is None
    assert w["error"] == "boom"
    assert w["tenant"] == "" and w["latency_ms"] == 0.0
