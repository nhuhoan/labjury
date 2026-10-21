from labjury.cost import CostMeter, TokenUsage


def test_record_accumulates():
    m = CostMeter()
    m.record(tokens_in=100, tokens_out=20, tenant="acme")
    m.record(tokens_in=50, tokens_out=10, tenant="acme")
    u = m.for_tenant("acme")
    assert (u.tokens_in, u.tokens_out, u.calls) == (150, 30, 2)


def test_for_tenant_unseen():
    m = CostMeter()
    u = m.for_tenant("nobody")
    assert (u.tokens_in, u.tokens_out, u.calls) == (0, 0, 0)
    assert m.snapshot() == {}  # for_tenant did not insert


def test_total_aggregates():
    m = CostMeter()
    m.record(tokens_in=100, tokens_out=20, tenant="a")
    m.record(tokens_in=5, tokens_out=1)  # untagged
    t = m.total()
    assert (t.tokens_in, t.tokens_out, t.calls) == (105, 21, 2)


def test_snapshot_is_copy():
    m = CostMeter()
    m.record(tokens_in=1, tokens_out=1, tenant="a")
    snap = m.snapshot()
    snap.clear()
    assert "a" in m.snapshot()  # mutating the copy didn't touch the meter


def test_cost_arithmetic():
    u = TokenUsage(tokens_in=2000, tokens_out=1000)
    assert u.total_tokens == 3000
    assert u.cost(in_per_1k=0.25, out_per_1k=1.25) == 2000 / 1000 * 0.25 + 1000 / 1000 * 1.25
    assert TokenUsage().cost(1.0, 1.0) == 0.0


def test_untagged_bucket():
    m = CostMeter()
    m.record(tokens_in=7, tokens_out=3)
    assert m.for_tenant(None).tokens_in == 7
    assert None in m.snapshot()
