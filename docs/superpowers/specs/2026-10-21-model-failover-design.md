# Model failover — a sibling composition in the resilience family

**Status:** design (CTO-decided; owner delegated, chose this extension) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Post-roadmap extension (Tier-1-adjacent, long-flagged). Completes the resilience wrapper family begun by `Reliable*`.

## Intent and the why

`Reliable*` makes one remote plugin survive its own flakiness (timeout/retry/breaker).
The named sibling it was always meant to have is **failover across several
interchangeable plugins**: when the primary model is down (or its breaker is open),
try the next. This is the standard "primary + fallback model" pattern, and it composes
*with* `Reliable*` rather than replacing it — each member of a failover group can
itself be a `ReliableScorer`.

Same philosophy as the rest of the family: a zero-dependency wrapper in front of the
plugin, no engine change; all members fail → the wrapper raises → the engine's
partial-failure path yields `ItemResult(FAILED)`.

## Goals

- **`FailoverScorer(scorers)`**, **`FailoverProposer(proposers)`**,
  **`FailoverContextBuilder(builders)`** in `labjury.reliability`:
  - Hold an ordered, non-empty list of interchangeable same-kind plugins; **empty list
    → `ValueError`** at construction.
  - Delegate the one async method to each member **in order**, returning the first
    member's result that does not raise.
  - Catch `Exception` (NOT `BaseException` — `asyncio.CancelledError` propagates),
    exactly as `Reliable*` does; on a member raising, move to the next.
  - **All members raise → re-raise the last exception** (fail-closed → engine FAILED).
  - `accepts = members[0].accepts` (members must be interchangeable — same modality);
    `FailoverContextBuilder` also sets `produces = members[0].produces`.
- Re-export `FailoverScorer`, `FailoverProposer`, `FailoverContextBuilder` from
  `labjury`; add to `test_public_api.py`.
- Extend `docs/reliability.md` with the failover section and the composition
  `FailoverScorer([ReliableScorer(primary), ReliableScorer(backup)])`.

## Non-goals / anti-goals

- **No parallel racing / hedging** (fan-out to all, take the first) — this is sequential
  primary→fallback. Hedging is a separate, costlier pattern.
- **No per-member health scoring, weighting, or sticky routing** — plain in-order
  failover; the breaker lives in each member's own `Reliable*` if wanted.
- **No modality reconciliation** — members are assumed interchangeable;
  `accepts`/`produces` come from the first. Mixing incompatible members is caller error.
- **No new dependency, no engine change, no plugin-contract change.**

## Constraints (inherited)

- Core `dependencies = []`; zero-dep mechanism in `labjury.reliability`; re-exported
  top-level (the wrappers themselves carry no deps). Core never imports contrib.
- Catch `Exception`, not `BaseException`.
- Python 3.11+. TDD throughout; commit per task.

## The parts of the how, as decided

```python
async def _failover(members, call):          # call(member) -> awaitable result
    last_exc: BaseException | None = None
    for member in members:
        try:
            return await call(member)
        except Exception as exc:              # CancelledError propagates
            last_exc = exc
    assert last_exc is not None               # ctor guarantees non-empty
    raise last_exc

class FailoverScorer:
    def __init__(self, scorers):
        if not scorers: raise ValueError("FailoverScorer needs at least one scorer")
        self._members = list(scorers)
        self.accepts = self._members[0].accepts
    async def score(self, state, questions):
        return await _failover(self._members, lambda m: m.score(state, questions))
```

`FailoverProposer`/`FailoverContextBuilder` follow the same shape for `propose` /
`build` (the latter also copying `produces`).

## What's left to the builder

- Nothing beyond the shapes above; the loop and the capability-attr copy are fixed.

## Review focus (inputs the tests must pin)

- **First member succeeds → its result is returned, later members not called** — Task 1.
- **Primary raises, fallback succeeds → fallback's result returned** (and the primary
  was tried first) — Task 1.
- **All members raise → the last exception propagates** — Task 1.
- **`asyncio.CancelledError` from a member propagates immediately** (not treated as a
  failover trigger) — Task 1.
- **Empty list → `ValueError`**; `accepts` (and `produces` for the builder) delegate
  from the first member; each wrapper is a structural `Scorer`/`Proposer`/`ContextBuilder`
  — Task 1.
