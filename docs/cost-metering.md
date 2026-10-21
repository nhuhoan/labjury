# Cost metering — tokens and dollars

`PerTenantUsage` ([multi-tenancy.md](multi-tenancy.md)) measures what the engine can
see itself: decision counts and latency, per tenant. But the **token** cost — the
number a finance team bills on — originates *inside* the scorer's `score()` call,
where the model returns its token usage. The four `Observer` hooks only receive an
`ItemResult`; they never see token counts, and adding tokens to `ItemResult` or the
`Observer`/`Scorer` protocols would break the public plugin contract.

So token accounting uses a **side channel**: a `CostMeter` your scorer reports into
directly.

## Who owns what

- **LabJury owns the counting** (`CostMeter` accumulates tokens and calls per tenant)
  **and the arithmetic** (`TokenUsage.cost` multiplies tokens by a rate).
- **You own the rate** — pricing is per-model, per-contract, and changes without
  notice; you pass it to `cost()`.
- **You own the reporting** — only your scorer knows its model's token accounting, so
  your scorer calls `record()`.

## Wiring it into a scorer

The meter is injected (DI, like every other backend); the engine never creates or
calls it. A scorer that doesn't report simply isn't metered.

```python
import labjury as lj

meter = lj.CostMeter()

class MyJevScorer:
    def __init__(self, client, meter):
        self._client, self._meter = client, meter

    async def score(self, state, questions):
        resp = await self._client.judge(...)
        self._meter.record(tokens_in=resp.usage.input, tokens_out=resp.usage.output)
        return resp.answers

engine = lj.Engine(..., scorer=MyJevScorer(client, meter))
```

## Reading the meter

```python
usage = meter.total()                      # TokenUsage across all tenants
usage.total_tokens                         # tokens_in + tokens_out
usage.cost(in_per_1k=0.25, out_per_1k=1.25)  # dollars at your rates

meter.for_tenant("acme")                   # one tenant's TokenUsage (zero if unseen)
meter.snapshot()                           # {tenant: TokenUsage} copy you can't mutate back
```

`record(tokens_in=…, tokens_out=…, tenant="acme")` tags usage by tenant; untagged
calls land in the `None` bucket. Pair it with `PerTenantUsage` keyed by the same
tenant and you have counts + latency + tokens + dollars per tenant.

## Non-goals

- **No price table.** LabJury ships no per-model rate, no currency, no
  provider-specific token math. You supply the rate.
- **No engine wiring / auto-metering.** The engine doesn't know the meter exists;
  you inject it into your scorer.
- **No contract change.** `Scorer`, `Observer`, and `ItemResult` are untouched — the
  meter is a side channel.
- **Single event loop.** `record()` has no `await`, so it's atomic within the
  asyncio loop the engine runs on; it is not a cross-OS-thread counter (same as
  `InMemoryObserver` / `PerTenantUsage`).
- **No tenant auto-propagation into `score()`.** `State` doesn't carry the tenant; if
  you want per-tenant token attribution, pass the tenant to `record()` from context
  your scorer holds.
