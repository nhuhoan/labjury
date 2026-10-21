# Metered scorer — token/$ cost accounting

**Status:** design (CTO-decided; owner delegated the post-roadmap "small extensions", one at a time — this is the LAST in the queue)
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap extension #4 (final). Named in the multi-tenancy note
as the documented extension: "token/$-level cost originates in the scorer, needs a
side channel; attribute with the same `tenant`."

## Intent and the why

`PerTenantUsage` already measures the model-agnostic cost signal the engine can see
itself: outcome counts and latency, per tenant, via the `Observer` hooks. But the
**token** cost — the thing a finance team actually bills — originates *inside* the
scorer's `score()` call (the model returns its token usage there). The four
`Observer` hooks only receive an `ItemResult`; they never see token counts, and
adding tokens to `ItemResult` or the `Observer`/`Scorer` contracts would break the
public plugin contract — which we do not do.

So token accounting needs a **side channel**: a small, zero-dependency accumulator
the deployer's scorer reports into directly. LabJury owns the *counting mechanism*
and the tokens×rate *arithmetic*; the deployer owns the *rate* (pricing is per-model,
per-contract deployer policy) and the *reporting* (only their scorer knows its
model's token accounting).

## Goals

- **`labjury.cost.TokenUsage`** — frozen value: `tokens_in: int`, `tokens_out: int`,
  `calls: int`; property `total_tokens` (= in + out); method
  `cost(in_per_1k: float, out_per_1k: float) -> float`
  (= `tokens_in/1000*in_per_1k + tokens_out/1000*out_per_1k`). The rates are the
  deployer's; the multiply is ours.
- **`labjury.cost.CostMeter`** — a side-channel accumulator:
  - `record(tokens_in: int = 0, tokens_out: int = 0, *, tenant: str | None = None) -> None`
    — one scorer call: adds the tokens and increments `calls` for that tenant
    (untagged traffic lands in the `None` bucket).
  - `for_tenant(tenant: str | None) -> TokenUsage` — that tenant's usage, or a fresh
    zero `TokenUsage`; never inserts, never raises (mirrors `PerTenantUsage.for_tenant`).
  - `total() -> TokenUsage` — summed across all tenants.
  - `snapshot() -> dict[str | None, TokenUsage]` — a copy the caller can't use to
    mutate the meter's state.
- Re-exported top-level (`CostMeter`, `TokenUsage`).

## How the deployer wires it (illustrative, not shipped)

```python
meter = lj.CostMeter()

class MyJevScorer:
    def __init__(self, client, meter): self._client, self._meter = client, meter
    async def score(self, state, questions):
        resp = await self._client.judge(...)
        self._meter.record(tokens_in=resp.usage.input, tokens_out=resp.usage.output)
        return resp.answers

# later / on a dashboard:
meter.total().cost(in_per_1k=0.25, out_per_1k=1.25)   # $ at the deployer's rates
```

## Non-goals / anti-goals

- **No pricing model shipped** — no per-model rate table, no currency, no
  provider-specific token math. The deployer passes the rate to `cost()`; the token
  counts come from their scorer. We never guess a price.
- **No Scorer/Observer/ItemResult contract change** — the meter is a side channel the
  scorer writes to; the engine, the plugin protocols, and `ItemResult` are untouched.
- **No engine wiring / auto-metering** — the engine never creates or calls a meter;
  the deployer injects it into their scorer (DI, like every other backend). A scorer
  that doesn't report simply isn't metered.
- **No locking / cross-thread guarantee** — `record()` has no `await`, so it is
  atomic within one asyncio event loop (where the engine runs); it is not a
  cross-OS-thread counter, exactly like `InMemoryObserver`/`PerTenantUsage`.
- **No automatic tenant propagation into `score()`** — `State` does not carry the
  tenant today, and this slice does not add it; a deployer who wants per-tenant token
  attribution passes the tenant to `record()` from context they hold. Per-tenant is
  supported by the meter; sourcing the tenant inside the scorer is the deployer's.

## Constraints (inherited)

- Zero-dep, lives in the package proper (`labjury.cost`), not `contrib` — it carries
  no dependency, like the reliability wrappers and `PerTenantUsage`.
- Python 3.11+. TDD; commit per task.

## Review focus (inputs the tests must pin)

- `record` accumulates `tokens_in`/`tokens_out`/`calls` per tenant across calls.
- `for_tenant` on an unseen tenant → a zero `TokenUsage`, and the meter did not grow
  (no insert).
- `total()` sums across tenants (including the `None` bucket).
- `snapshot()` returns a copy — mutating it (or exhausting it) does not change the
  meter.
- `TokenUsage.cost(in, out)` arithmetic and `total_tokens`; a zero-usage tenant costs
  `0.0`.
- Untagged (`tenant=None`) usage is tracked in its own bucket.
