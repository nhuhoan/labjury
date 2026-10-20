import pytest

from labjury.plugins import Scorer
from labjury.testing import assert_plugin_conforms


class _GoodScorer:
    accepts = frozenset({"text"})

    async def score(self, state, questions):
        return []


class _SyncScorer:
    accepts = frozenset({"text"})

    def score(self, state, questions):  # not async
        return []


class _BadAccepts:
    accepts = {"text"}  # set, not frozenset

    async def score(self, state, questions):
        return []


class _NoScore:
    accepts = frozenset({"text"})  # missing score


def test_conforms_passes_good_scorer():
    assert_plugin_conforms(_GoodScorer(), Scorer)  # no raise


def test_conforms_rejects_sync_method():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_SyncScorer(), Scorer)


def test_conforms_rejects_non_frozenset_accepts():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_BadAccepts(), Scorer)


def test_conforms_rejects_missing_method():
    with pytest.raises(AssertionError):
        assert_plugin_conforms(_NoScore(), Scorer)
