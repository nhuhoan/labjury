import asyncio

import pytest

from labjury import (
    Action,
    Answer,
    Candidate,
    ChoiceQuestion,
    Content,
    Item,
    NoulQuestion,
    State,
    Status,
    Verdict,
)
from labjury.defaults import CollectingSink, InMemoryCache
from labjury.engine import Engine
from labjury.observability import InMemoryObserver
from labjury.policies import RecallBiasedPolicy
from labjury.taxonomy import InMemoryTaxonomyStore


# ---- fakes ----------------------------------------------------------------

class _TextBuilder:
    accepts = frozenset({"*"})
    produces = frozenset({"text"})

    def __init__(self, fail_on_id=None):
        self._fail_on_id = fail_on_id

    async def build(self, item, state):
        if self._fail_on_id is not None and item.id == self._fail_on_id:
            raise RuntimeError("boom")
        if isinstance(item.raw, dict) and "text" in item.raw:
            state.add(Content("text", item.raw["text"]))
        return state


class _FoodProposer:
    accepts = frozenset({"*"})

    def __init__(self):
        self.calls = 0

    async def propose(self, state):
        self.calls += 1
        return [Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))]


class _FakeScorer:
    accepts = frozenset({"*"})

    def __init__(self, confidence=0.95, slow=False):
        self._confidence = confidence
        self._slow = slow

    async def score(self, state, questions):
        if self._slow:
            await asyncio.sleep(0.05)
        return [Answer(q.key, value="food", confidence=self._confidence) for q in questions]


class _ImageBuilder:
    accepts = frozenset({"*"})
    produces = frozenset({"image"})

    async def build(self, item, state):
        state.add(Content("image", item.raw["image"]))
        return state


class _ImageScorer:
    accepts = frozenset({"image"})

    def __init__(self, answer=None):
        self._answer = answer
        self.calls = 0

    async def score(self, state, questions):
        self.calls += 1
        return [self._answer] if self._answer is not None else []


# ---- fixtures / helpers ---------------------------------------------------

def make_engine(track_proposer=False, fail_on_id=None, max_concurrency=64, slow_scorer=False):
    proposer = _FoodProposer()
    eng = Engine(
        context_builders=[_TextBuilder(fail_on_id=fail_on_id)],
        proposers=[proposer],
        scorers=[_FakeScorer(slow=slow_scorer)],
        policy=RecallBiasedPolicy(),
        sink=CollectingSink(),
        cache=InMemoryCache(),
        taxonomy=InMemoryTaxonomyStore(),
        observer=InMemoryObserver(),
        max_concurrency=max_concurrency,
    )
    if track_proposer:
        return eng, proposer
    return eng


def _image_engine(standing_candidates=None, scorer=None):
    return Engine(
        context_builders=[_ImageBuilder()],
        proposers=[],
        scorers=[scorer],
        policy=RecallBiasedPolicy(),
        sink=CollectingSink(),
        cache=InMemoryCache(),
        taxonomy=InMemoryTaxonomyStore(),
        observer=InMemoryObserver(),
        standing_candidates=standing_candidates,
    )


# ---- tests ----------------------------------------------------------------

async def test_end_to_end_accept():
    eng = make_engine()
    r = await eng.process(Item("i1", raw={"text": "món ăn ngon"}))
    assert r.status is Status.DECIDED
    assert r.verdict.action is Action.ACCEPT and r.correlation_id == "i1"


async def test_cache_hit_skips_expensive_stages():
    eng, proposer = make_engine(track_proposer=True)
    item = Item("i1", {"text": "x"})
    await eng.cache.put(eng._key(item), Verdict(Action.ACCEPT, ["food"], {}, [], "cached"))
    r = await eng.process(item)
    assert r.verdict.reason == "cached" and proposer.calls == 0


async def test_batch_results_unordered_but_complete():
    eng = make_engine()
    items = [Item(f"i{n}", {"text": "t"}) for n in range(5)]
    results = await eng.process_batch(items)
    assert {r.correlation_id for r in results} == {f"i{n}" for n in range(5)}


async def test_one_failing_item_does_not_fail_batch():
    eng = make_engine(fail_on_id="i2")
    # distinct raw per item: identical raw would collide in the decision cache
    results = {
        r.correlation_id: r
        for r in await eng.process_batch(
            [Item("i1", {"text": "one"}), Item("i2", {"text": "two"})]
        )
    }
    assert results["i2"].status is Status.FAILED
    assert results["i1"].status in (Status.DECIDED, Status.REVIEW)


async def test_saturation_returns_retry_later():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    results = await eng.process_batch([Item(f"i{n}", {"text": "t"}) for n in range(4)])
    assert any(r.status is Status.RETRY_LATER for r in results)


async def test_visual_fast_path_scores_standing_candidates():
    standing = [Candidate("nudity", "violation", NoulQuestion("nudity", "contains nudity?"))]
    scorer = _ImageScorer(answer=Answer("nudity", value=True, confidence=0.95))
    eng = _image_engine(standing_candidates=standing, scorer=scorer)
    r = await eng.process(Item("v1", {"image": b"img"}))
    assert r.status is Status.REVIEW  # confident violation held, proposer never consulted


async def test_fast_path_without_standing_candidates_fails_item():
    eng = _image_engine(standing_candidates=None, scorer=_ImageScorer(answer=None))
    r = await eng.process(Item("v2", {"image": b"img"}))
    assert r.status is Status.FAILED
