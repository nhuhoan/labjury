import pytest

from labjury.guards import (
    GuardedProposer,
    GuardedScorer,
    GuardRejected,
)
from labjury.plugins import Proposer, ProposalContext, Scorer
from labjury.state import Content, State


class _RecordingScorer:
    accepts = frozenset({"*"})

    def __init__(self) -> None:
        self.seen = None

    async def score(self, state, questions):
        self.seen = state
        return []


class _RecordingProposer:
    accepts = frozenset({"*"})

    def __init__(self) -> None:
        self.seen = None

    async def propose(self, state, context):
        self.seen = state
        return []


class _AllowGuard:
    async def inspect(self, state) -> None:
        return None


class _RejectGuard:
    async def inspect(self, state) -> None:
        raise GuardRejected("nope")


async def test_guarded_scorer_rejection_propagates_without_calling_inner():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    with pytest.raises(GuardRejected):
        await GuardedScorer(inner, _RejectGuard()).score(s, [])
    assert inner.seen is None


async def test_guarded_scorer_passes_original_state_when_guard_allows():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    out = await GuardedScorer(inner, _AllowGuard()).score(s, [])
    assert inner.seen is s  # original, unmodified
    assert out == []


async def test_guarded_proposer_rejection_propagates_without_calling_inner():
    inner = _RecordingProposer()
    s = State()
    s.add(Content("text", "hi"))
    with pytest.raises(GuardRejected):
        await GuardedProposer(inner, _RejectGuard()).propose(s, ProposalContext())
    assert inner.seen is None


def test_guarded_scorer_is_a_scorer():
    assert isinstance(GuardedScorer(_RecordingScorer(), _AllowGuard()), Scorer)
    assert GuardedScorer(_RecordingScorer(), _AllowGuard()).accepts == frozenset({"*"})


def test_guarded_proposer_is_a_proposer():
    assert isinstance(GuardedProposer(_RecordingProposer(), _AllowGuard()), Proposer)
