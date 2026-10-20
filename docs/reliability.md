# Reliability — wrapping any remote plugin against hangs and flaps

A remote plugin — any `Scorer`, `Proposer`, or `ContextBuilder` backed by a
network model — will eventually hang, flap, or fall over. LabJury ships one
**model-agnostic standard** for making such a plugin reliable: wrap it in
`ReliableScorer`, `ReliableProposer`, or `ReliableContextBuilder`. Nothing here
is tied to Jev or any particular backend — it wraps *any* plugin of that kind,
the same way `Jev` is just one `Scorer`.

The wrappers are **zero-dependency** and live in the package proper
(`labjury.reliability`), re-exported from the top level:

```python
import labjury as lj
lj.ReliableScorer, lj.ReliableProposer, lj.ReliableContextBuilder, lj.CircuitOpenError
```

## The three behaviors

Each wrapper applies `breaker(retry(timeout(call)))` to the plugin's one async
method — the order matters:

1. **timeout** — bounds a single attempt. Applied **per attempt**, so a retry
   gets a fresh deadline, not the remainder of the first one.
2. **retry** — re-invokes the method on failure, with exponential backoff
   between attempts.
3. **circuit breaker** — after enough consecutive failures the breaker opens
   and fast-fails with `CircuitOpenError` *without calling the plugin*, sparing
   a backend that is already down. After a cooldown it allows one half-open
   trial; success closes it, failure re-opens it.

### Knobs and defaults

All are keyword arguments to the wrapper's constructor:

| knob | default | meaning |
|---|---|---|
| `timeout_s` | `5.0` | per-attempt timeout in seconds; `None` disables |
| `retries` | `2` | retries *after* the first attempt (so up to 3 calls) |
| `backoff_base_s` | `0.1` | first backoff; doubles each retry |
| `backoff_max_s` | `2.0` | backoff ceiling |
| `failure_threshold` | `5` | consecutive failures that open the breaker; `0` disables the breaker |
| `reset_timeout_s` | `30.0` | cooldown before a half-open trial |

`asyncio.CancelledError` is **not** caught — cancellation propagates cleanly and
is never retried.

## Wrapped methods must be read-only / idempotent

Retry repeats the call, so only wrap methods with no side effects — scoring,
proposing, ASR/OCR all qualify. Wrapping a side-effecting method is the caller's
mistake: a retry would run the side effect twice.

## How a give-up surfaces

When a wrapper times out, exhausts its retries, or trips its breaker, it simply
**raises** (the last underlying exception, a `TimeoutError`, or
`CircuitOpenError`). The engine's existing partial-failure path turns that into
an `ItemResult(status=FAILED)` for that item — the rest of the batch is
unaffected. The caller re-enqueues failed items on their own schedule. No engine
change is needed; the wrapper composes in front of the plugin.

## Usage

```python
import labjury as lj
from labjury.contrib.jev import JevScorer  # any remote Scorer

engine = lj.Engine(
    ...,
    scorers=[lj.ReliableScorer(JevScorer(...), timeout_s=2.0)],
)
```

`ReliableProposer` and `ReliableContextBuilder` wrap their kinds the same way and
delegate `accepts` (and `produces`, for context builders) to the inner plugin, so
a wrapped plugin routes exactly like the plugin it wraps.

## Failover across models

Per-plugin reliability keeps one model alive through its own flakiness. Failing
over to a **different** model when the primary gives up is the sibling
composition: `FailoverScorer`, `FailoverProposer`, `FailoverContextBuilder` hold
an ordered list of interchangeable same-kind plugins and try them in turn,
returning the first that does not raise.

```python
scorer = lj.FailoverScorer([
    lj.ReliableScorer(primary_model),     # tried first; its own timeout/retry/breaker
    lj.ReliableScorer(backup_model),      # used only if the primary raises
])
```

- Members are tried **in order**; the first success short-circuits the rest.
- A member raising (including a `Reliable*` that exhausted its retries or whose
  breaker is open) moves on to the next.
- **All members raise → the last exception propagates** → the engine's
  partial-failure path yields `ItemResult(FAILED)`. Same fail-closed contract as
  the rest of the family.
- `asyncio.CancelledError` from a member propagates immediately — it is not a
  failover trigger.
- An empty list is a `ValueError`; `accepts` (and `produces` for the context
  builder) are delegated from the first member, so members must be
  interchangeable (same modality).

Failover composes *with* `Reliable*` — each member is typically a `Reliable*`
wrapper, so every model gets its own timeout/retry/breaker before failover
reaches for the next. This is sequential primary→fallback, not parallel
hedging.
