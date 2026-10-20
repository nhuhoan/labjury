"""The remote-plugin reliability standard — model-agnostic, zero-dependency.

A remote plugin (any ``Scorer`` / ``Proposer`` / ``ContextBuilder`` backed by a
network model) will eventually hang or flap. These wrappers make *any* such
plugin reliable by applying ``breaker(retry(timeout(call)))`` to its one async
method — nothing here is tied to Jev or any backend.

A wrapper that times out, exhausts its retries, or trips its breaker simply
**raises**; the engine's existing partial-failure path turns that into an
``ItemResult(FAILED)`` for the caller to re-enqueue. No engine change is needed —
the wrapper composes in front of the plugin.

The wrapped method must be **read-only / idempotent** (scoring, proposing,
ASR/OCR have no side effects) — retry repeats the call, so wrapping a
side-effecting method is the caller's mistake.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised instead of calling the inner plugin while the breaker is open."""


class _Reliable:
    """Shared runner: ``breaker(retry(timeout(call)))`` with per-wrapper state."""

    def __init__(
        self,
        *,
        timeout_s: float | None,
        retries: int,
        backoff_base_s: float,
        backoff_max_s: float,
        failure_threshold: int,
        reset_timeout_s: float,
        clock: Callable[[], float],
    ) -> None:
        self._timeout_s = timeout_s
        self._retries = retries
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._clock = clock
        self._failures = 0
        self._open = False
        self._opened_at = 0.0

    def _breaker_enabled(self) -> bool:
        return self._failure_threshold > 0

    def _on_success(self) -> None:
        self._failures = 0
        self._open = False

    def _on_failure(self) -> None:
        self._failures += 1
        if self._breaker_enabled() and self._failures >= self._failure_threshold:
            self._open = True
            self._opened_at = self._clock()

    async def run(self, make_awaitable: Callable[[], Awaitable[T]]) -> T:
        if self._breaker_enabled() and self._open:
            if self._clock() - self._opened_at < self._reset_timeout_s:
                raise CircuitOpenError("circuit is open")
            # window elapsed -> allow one half-open trial (fall through)

        last_exc: BaseException | None = None
        for attempt in range(self._retries + 1):
            try:
                aw = make_awaitable()
                if self._timeout_s is not None:
                    result = await asyncio.wait_for(aw, self._timeout_s)
                else:
                    result = await aw
            except Exception as exc:  # NOT BaseException: CancelledError propagates
                last_exc = exc
                self._on_failure()
                if attempt < self._retries:
                    await asyncio.sleep(
                        min(self._backoff_base_s * 2**attempt, self._backoff_max_s)
                    )
                    continue
                raise
            else:
                self._on_success()
                return result
        assert last_exc is not None  # unreachable: loop returns or raises
        raise last_exc


_DEFAULTS = dict(
    timeout_s=5.0,
    retries=2,
    backoff_base_s=0.1,
    backoff_max_s=2.0,
    failure_threshold=5,
    reset_timeout_s=30.0,
    clock=time.monotonic,
)


class ReliableScorer:
    def __init__(self, inner, **kwargs) -> None:
        self._inner = inner
        self.accepts = inner.accepts
        self._runner = _Reliable(**{**_DEFAULTS, **kwargs})

    async def score(self, state, questions):
        return await self._runner.run(lambda: self._inner.score(state, questions))


class ReliableProposer:
    def __init__(self, inner, **kwargs) -> None:
        self._inner = inner
        self.accepts = inner.accepts
        self._runner = _Reliable(**{**_DEFAULTS, **kwargs})

    async def propose(self, state, context):
        return await self._runner.run(lambda: self._inner.propose(state, context))


class ReliableContextBuilder:
    def __init__(self, inner, **kwargs) -> None:
        self._inner = inner
        self.accepts = inner.accepts
        self.produces = inner.produces
        self._runner = _Reliable(**{**_DEFAULTS, **kwargs})

    async def build(self, item, state):
        return await self._runner.run(lambda: self._inner.build(item, state))


# -- failover: the sibling composition -----------------------------------------
# Try interchangeable same-kind plugins in order; return the first that does not
# raise. All raise -> re-raise the last (fail-closed -> engine FAILED). Composes
# with Reliable* (a member may itself be a ReliableScorer).


async def _failover(members: list, call: Callable[[object], Awaitable[T]]) -> T:
    last_exc: BaseException | None = None
    for member in members:
        try:
            return await call(member)
        except Exception as exc:  # NOT BaseException: CancelledError propagates
            last_exc = exc
    assert last_exc is not None  # ctor guarantees a non-empty member list
    raise last_exc


class FailoverScorer:
    def __init__(self, scorers) -> None:
        self._members = list(scorers)
        if not self._members:
            raise ValueError("FailoverScorer needs at least one scorer")
        self.accepts = self._members[0].accepts

    async def score(self, state, questions):
        return await _failover(self._members, lambda m: m.score(state, questions))


class FailoverProposer:
    def __init__(self, proposers) -> None:
        self._members = list(proposers)
        if not self._members:
            raise ValueError("FailoverProposer needs at least one proposer")
        self.accepts = self._members[0].accepts

    async def propose(self, state, context):
        return await _failover(self._members, lambda m: m.propose(state, context))


class FailoverContextBuilder:
    def __init__(self, builders) -> None:
        self._members = list(builders)
        if not self._members:
            raise ValueError("FailoverContextBuilder needs at least one builder")
        self.accepts = self._members[0].accepts
        self.produces = self._members[0].produces

    async def build(self, item, state):
        return await _failover(self._members, lambda m: m.build(item, state))
