import asyncio

import pytest

from labjury.decisions import Answer, Candidate, ChoiceQuestion
from labjury.plugins import ContextBuilder, Proposer, ProposalContext, Scorer
from labjury.reliability import (
    CircuitOpenError,
    ReliableContextBuilder,
    ReliableProposer,
    ReliableScorer,
)

_Q = [ChoiceQuestion("q", "?", ["x"])]
_OK = [Answer("q", value="x", confidence=1.0)]


class FlakyScorer:
    accepts = frozenset({"*"})

    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times

    async def score(self, state, questions):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return list(_OK)


class HangingScorer:
    accepts = frozenset({"*"})

    def __init__(self):
        self.calls = 0

    async def score(self, state, questions):
        self.calls += 1
        await asyncio.Event().wait()  # never returns


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def advance(self, dt):
        self.t += dt


async def test_retry_succeeds_after_transient_failures():
    inner = FlakyScorer(fail_times=2)
    rel = ReliableScorer(inner, retries=2, backoff_base_s=0.0, timeout_s=None)
    assert await rel.score(None, _Q) == _OK
    assert inner.calls == 3


async def test_retry_exhausted_reraises():
    inner = FlakyScorer(fail_times=3)
    rel = ReliableScorer(inner, retries=2, backoff_base_s=0.0, timeout_s=None)
    with pytest.raises(RuntimeError):
        await rel.score(None, _Q)


async def test_timeout_applies_per_attempt():
    inner = HangingScorer()
    rel = ReliableScorer(
        inner, timeout_s=0.01, retries=1, backoff_base_s=0.0, failure_threshold=0
    )
    with pytest.raises(TimeoutError):
        await rel.score(None, _Q)
    assert inner.calls == 2  # each attempt was bounded and retried once


async def test_breaker_opens_and_fast_fails_without_calling_inner():
    inner = FlakyScorer(fail_times=999)
    rel = ReliableScorer(inner, retries=0, timeout_s=None, failure_threshold=3)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)
    assert inner.calls == 3
    with pytest.raises(CircuitOpenError):
        await rel.score(None, _Q)
    assert inner.calls == 3  # inner not called while open


async def test_breaker_half_open_closes_on_success():
    inner = FlakyScorer(fail_times=2)
    clock = FakeClock()
    rel = ReliableScorer(
        inner,
        retries=0,
        timeout_s=None,
        failure_threshold=2,
        reset_timeout_s=10.0,
        clock=clock.now,
    )
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)
    with pytest.raises(CircuitOpenError):
        await rel.score(None, _Q)
    clock.advance(11.0)
    assert await rel.score(None, _Q) == _OK  # half-open trial succeeds -> closed
    assert await rel.score(None, _Q) == _OK


async def test_breaker_disabled_never_opens():
    inner = FlakyScorer(fail_times=999)
    rel = ReliableScorer(inner, retries=0, timeout_s=None, failure_threshold=0)
    for _ in range(10):
        with pytest.raises(RuntimeError):
            await rel.score(None, _Q)  # RuntimeError, never CircuitOpenError
    assert inner.calls == 10


def test_reliable_scorer_is_a_scorer():
    rel = ReliableScorer(FlakyScorer(0))
    assert isinstance(rel, Scorer) and rel.accepts == frozenset({"*"})


class FlakyProposer:
    accepts = frozenset({"*"})

    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times

    async def propose(self, state, context):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return [Candidate("food", "tag", ChoiceQuestion("q", "?", ["food"]))]


class FlakyBuilder:
    accepts = frozenset({"text"})
    produces = frozenset({"json"})

    def __init__(self, fail_times):
        self.calls = 0
        self._fail = fail_times

    async def build(self, item, state):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")
        return state


async def test_reliable_proposer_retries_and_is_a_proposer():
    inner = FlakyProposer(fail_times=1)
    rel = ReliableProposer(inner, retries=1, backoff_base_s=0.0, timeout_s=None)
    out = await rel.propose(None, ProposalContext())
    assert out and inner.calls == 2
    assert isinstance(rel, Proposer) and rel.accepts == frozenset({"*"})


async def test_reliable_context_builder_delegates_accepts_and_produces():
    inner = FlakyBuilder(fail_times=1)
    rel = ReliableContextBuilder(inner, retries=1, backoff_base_s=0.0, timeout_s=None)
    state = object()
    assert await rel.build(None, state) is state and inner.calls == 2
    assert isinstance(rel, ContextBuilder)
    assert rel.accepts == frozenset({"text"}) and rel.produces == frozenset({"json"})
