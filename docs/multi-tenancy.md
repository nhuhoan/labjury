# Multi-tenancy & per-tenant cost

One LabJury deployment usually serves many tenants — companies, teams, brands.
Two needs follow: **attribution** (trace every decision to the tenant it was made
for) and **per-tenant cost** (know who is consuming the budget). LabJury carries
the tenant identity and measures the usage it can see; it does not partition your
storage or convert usage to money — those are yours.

## Attribution: the `tenant` field

An `Item` carries an optional tenant:

```python
import labjury as lj

item = lj.Item("post-42", {"text": "…"}, tenant="acme")
result = await engine.process(item)

result.tenant          # "acme"
```

The engine copies `item.tenant` onto every `ItemResult` it produces and records it
on every `AuditEvent` (the full decision event and the cache-hit event). It never
*reads* tenant to make a decision — it only attributes outputs. So:

- your **sink** and **observer** see `result.tenant` and can route/aggregate by it;
- your **audit store** receives `event.tenant` in `to_dict()`, so you can partition
  or query the trail per tenant.

LabJury does **not** shard any store by tenant. You bring your own storage and key
it however you like — the framework just carries the identity through so your
stores and dashboards can use it. Records written before you adopted `tenant`
decode to `tenant=None`.

## Per-tenant cost: `PerTenantUsage`

`PerTenantUsage` is an `Observer` that buckets usage by `result.tenant`:

```python
usage = lj.PerTenantUsage()
engine = lj.Engine(..., observer=usage)

# after processing …
acme = usage.for_tenant("acme")
acme.decided, acme.review, acme.failed, acme.retry_later   # outcome counts
acme.avg_latency_ms                                        # mean decision latency
usage.snapshot()                                           # {tenant: TenantUsage, …}
```

`for_tenant` on an unseen tenant returns a fresh zero tally (never `KeyError`).
Untagged traffic (`tenant=None`) lands in its own bucket. Latency accumulates only
for results that carry one — a pre-admission `RETRY_LATER` (pure backpressure, no
work done) counts but contributes no latency.

This is the **model-agnostic** cost signal the engine owns end to end: decision
counts and latency. A **dollar** figure is yours — multiply the usage by the rate
you pay for the model behind your scorer. Model pricing is policy; LabJury doesn't
encode it.

### Running it beside another observer

The engine takes a single observer, so compose with `FanOutObserver`:

```python
usage = lj.PerTenantUsage()
engine = lj.Engine(..., observer=lj.FanOutObserver([usage, prometheus_observer]))
```

`FanOutObserver` forwards each of the four hooks to every child, in order.

## Non-goals

- **No storage partitioning.** LabJury carries the tenant; your stores key on it.
- **No token or dollar cost.** Token counts originate in the scorer and depend on
  model pricing; reporting them would change the `Scorer` contract and encode
  pricing policy. A scorer that wants token-level accounting can report it through
  its own side channel and attribute it with the same `tenant` on the item.
- **No per-tenant rate limiting or quota.** That is admission control — a different
  mechanism from attribution and measurement.
