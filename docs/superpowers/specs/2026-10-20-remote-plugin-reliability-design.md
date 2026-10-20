# Remote-plugin reliability — the standard — design

**Date:** 2026-10-20
**Tier / step:** Enterprise readiness — Tier 1, step 4 (remote-plugin reliability).
**Depends on:** the `ContextBuilder` / `Proposer` / `Scorer` protocols
(`src/labjury/plugins.py`) and the engine's existing partial-failure contract
(`process` turns any raising plugin into an `ItemResult(FAILED)`).

## Intent and the why

A plugin backed by a network model — a Jev scorer, an LLM proposer, an ASR
context builder — will eventually hang, flap, or fail. When it does, that must
not hang the engine or silently corrupt a decision. LabJury needs a **standard**
for making a remote plugin reliable.

The owner's steer is the design's north star: **Jev is just one model; there
will be others of the same kind, better, later. What matters is that we define
the standard, not that we integrate a model.** So this ships nothing
Jev-specific and nothing tied to any backend. It ships a **model-agnostic,
composable reliability standard** that wraps *any* plugin satisfying the three
remote-facing protocols — timeout, retry, and circuit-breaker — so adopting a
better same-kind model later is just wrapping that model in the same standard.

## Why composition, in core, with no engine change

- **Composition (wrappers), not engine-level and not plugin-internal.** The
  engine owns mechanisms, but not every plugin is remote — an
  `InMemoryTaxonomyStore` or a local scorer must not be forced through a
  timeout. Putting reliability in the engine would wrap the innocent; putting it
  inside each plugin would make every plugin author re-implement it,
  inconsistently. A wrapper the deployer composes around *the plugins that are
  remote* is opt-in, uniform, and model-agnostic — one standard, applied where
  it belongs.
- **In core, not contrib.** The reliability triad is pure `asyncio`/stdlib —
  **zero dependency**. The contrib rule is "contrib may carry deps; core stays
  dependency-free"; a zero-dep mechanism that *is* the framework's reliability
  standard belongs in the framework namespace, like the dependency-free
  `LLMJudgeScorer`. It wraps core protocol types, so it lives in core
  (`labjury.reliability`) and is re-exported from top-level `labjury`.
- **No engine change.** A wrapper that times out, exhausts its retries, or trips
  its breaker simply **raises**; the engine's existing partial-failure path
  turns that into `ItemResult(FAILED)`, which the caller re-enqueues. The
  reliability standard needs not a single line of engine change — it composes in
  front of the plugin.

## The three behaviors and their composition

Applied **breaker( retry( timeout( call ) ) )** — timeout bounds each attempt,
retry repeats attempts, the breaker guards the whole against a flapping
dependency:

- **Timeout** — `asyncio.wait_for(awaitable, timeout_s)`; on exceed the attempt
  raises `TimeoutError`.
- **Retry** — up to `retries` additional attempts after the first, with
  exponential backoff (`backoff_base_s * 2**attempt`, capped at `backoff_max_s`)
  via `asyncio.sleep`; the last error re-raises on exhaustion. Safe because all
  three wrapped methods are **read-only** (scoring, proposing, ASR/OCR have no
  side effects), so repeating a call cannot double-commit anything.
- **Circuit-breaker** — a 3-state machine (closed → open → half-open). After
  `failure_threshold` consecutive failures it **opens** and rejects fast with
  `CircuitOpenError` for `reset_timeout_s`; then it goes **half-open**, allowing
  one trial — success closes it, failure re-opens it. This protects a struggling
  downstream from a thundering herd and fails items fast instead of piling up
  timeouts. State is per-wrapper, in-process; under single-threaded `asyncio`
  the counters need no lock.

## Goals

- A model-agnostic reliability standard in `labjury.reliability`, zero new
  dependency, re-exported from top-level `labjury`.
- Three composable wrappers, each satisfying the protocol it wraps and
  delegating its capability attributes:
  - `ReliableScorer(inner: Scorer, ...)` → `Scorer`, delegates `accepts`.
  - `ReliableProposer(inner: Proposer, ...)` → `Proposer`, delegates `accepts`.
  - `ReliableContextBuilder(inner: ContextBuilder, ...)` → `ContextBuilder`,
    delegates `accepts` **and** `produces`.
- `CircuitOpenError` raised when the breaker is open.
- Deterministic, fast tests (injected clock for the breaker's reset window; no
  real 30-second sleeps).

## Non-goals

- **No fallback / failover across models** this step. It is the natural sibling
  that the "multiple same-kind models" steer points to — run a primary and fail
  over to a backup — but it composes *several* plugins, a different axis from
  making *one* reliable. It builds cleanly on this standard and is the obvious
  next slice; kept out to land this one solid.
- No rate-limiting, bulkhead, or concurrency cap (the engine already bounds
  concurrency).
- No persistence of breaker state across process restarts (in-process only).
- No engine change; no new dependency; nothing Jev- or backend-specific.
- No retry budget shared across items (per-call retries only).

## Anti-goals (failure even if it works)

- The core importing any HTTP/model library or `labjury.contrib`.
- Breaking existing plugins — the wrappers are strictly opt-in composition.
- Retrying a non-idempotent operation (the wrapped methods are read-only;
  documented so no one wraps a side-effecting method expecting safety).
- A breaker whose state is shared between unrelated dependencies.

## The how — decided

**Module:** `src/labjury/reliability.py` (core), re-exported from
`src/labjury/__init__.py`: `ReliableScorer`, `ReliableProposer`,
`ReliableContextBuilder`, `CircuitOpenError`.

**Shared config (constructor keyword args, same on all three wrappers), with
defaults:**
`timeout_s: float | None = 5.0`, `retries: int = 2`, `backoff_base_s: float =
0.1`, `backoff_max_s: float = 2.0`, `failure_threshold: int = 5`,
`reset_timeout_s: float = 30.0`, `clock: Callable[[], float] = time.monotonic`.
`timeout_s=None` disables the timeout; `retries=0` disables retry;
`failure_threshold<=0` disables the breaker — so a deployer dials in exactly the
behaviors they want.

**Internal factoring (builder's choice, DRY):** the triad logic is written once
— a small internal runner holding the config and the breaker state with an
`async def run(self, make_awaitable: Callable[[], Awaitable[T]]) -> T` — and each
wrapper owns one runner and calls it from its single protocol method, passing a
zero-arg factory that invokes the inner plugin. `make_awaitable` is a factory
(not a bare awaitable) because retry must create a *fresh* awaitable per attempt.

**Wrappers:** each stores `inner` and a runner; `accepts = inner.accepts` (and
`ReliableContextBuilder.produces = inner.produces`) read at construction; the one
method (`score` / `propose` / `build`) delegates through the runner.

## What's left to the builder

- Exact backoff arithmetic and the breaker state transitions; the internal
  runner's shape.
- Tests (`tests/test_reliability.py`), with deterministic fakes and an injected
  clock:
  - a plugin that fails `retries` times then succeeds → the wrapper returns the
    success (retry works);
  - a plugin that fails `retries + 1` times → the wrapper re-raises the last
    error;
  - a plugin that hangs → with a small `timeout_s` the wrapper raises
    `TimeoutError` (use an `asyncio.Event` that is never set, or a sleep longer
    than the timeout);
  - after `failure_threshold` consecutive failures the next call raises
    `CircuitOpenError` **without** calling the inner plugin (assert the inner
    call count did not increase);
  - advancing the injected clock past `reset_timeout_s` lets one trial through
    (half-open), and a success closes the breaker;
  - `isinstance(ReliableScorer(fake), Scorer)` is `True`; `accepts` is delegated;
    `ReliableContextBuilder` delegates `produces` too.
- `src/labjury/__init__.py` re-exports and `tests/test_public_api.py` coverage
  for the new names.
- Docs: new `docs/reliability.md` (the standard, the three knobs, the
  read-only/idempotent caveat, that failures surface as `FAILED` via the engine,
  and that failover across models is the sibling composition); one-line pointers
  in `README.md` and `README.vi.md`.

## Builder check

Self builder-check (standing no-spawn-without-asking constraint; weaker than an
independent reviewer, noted as such). Open question a builder would raise and its
settled answer: *"Under `process_batch`, many items hit one `ReliableScorer`
concurrently — is the breaker's shared counter safe?"* — Yes. `asyncio` is
single-threaded; the counter is only read/written at `await` boundaries within
one event loop, so there is no torn update. Concurrent in-flight calls at the
moment the breaker trips may still complete — acceptable and standard for an
in-process breaker. Settled; recorded here.
