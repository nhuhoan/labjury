from labjury import Action, ItemResult, Status, Verdict


def test_item_result_carries_correlation_id():
    r = ItemResult(
        "item-42",
        Status.DECIDED,
        verdict=Verdict(Action.ACCEPT, ["food"], {"food": 0.98}, [], "ok"),
    )
    assert r.correlation_id == "item-42" and r.verdict.action is Action.ACCEPT


def test_retry_later_needs_no_verdict():
    r = ItemResult("item-7", Status.RETRY_LATER)
    assert r.verdict is None and r.status is Status.RETRY_LATER


def test_failed_carries_error():
    r = ItemResult("item-9", Status.FAILED, error="scorer timeout")
    assert r.error == "scorer timeout"
