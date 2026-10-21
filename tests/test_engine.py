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
from labjury.defaults import CollectingSink, InMemoryAuditLog, InMemoryCache
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

    async def propose(self, state, context):
        self.calls += 1
        return [Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))]


class _CapturingProposer:
    accepts = frozenset({"*"})

    def __init__(self):
        self.seen_known_labels = None

    async def propose(self, state, context):
        self.seen_known_labels = set(context.known_labels)
        return [Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))]


class _FakeScorer:
    accepts = frozenset({"*"})

    def __init__(self, confidence=0.95, slow=False):
        self._confidence = confidence
        self._slow = slow
        self.calls = 0

    async def score(self, state, questions):
        self.calls += 1
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

def make_engine(track_proposer=False, fail_on_id=None, max_concurrency=64, slow_scorer=False,
                audit=None):
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
        audit=audit,
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


async def test_cache_hit_skips_scoring():
    eng, proposer = make_engine(track_proposer=True)
    item = Item("i1", {"text": "x"})
    await eng.process(item)
    r = await eng.process(item)
    assert r.verdict.reason == "accepted" and proposer.calls == 2
    assert eng._scorers[0].calls == 1


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


async def test_concurrent_batches_share_one_limit():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    first, second = await asyncio.gather(
        eng.process_batch([Item("a", {"text": "a"})]),
        eng.process_batch([Item("b", {"text": "b"})]),
    )
    assert {first[0].status, second[0].status} == {
        Status.DECIDED, Status.RETRY_LATER
    }


async def test_direct_process_respects_same_limit():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    first, second = await asyncio.gather(
        eng.process(Item("a", {"text": "a"})),
        eng.process(Item("b", {"text": "b"})),
    )
    assert {first.status, second.status} == {Status.DECIDED, Status.RETRY_LATER}
    retry = next(r for r in (first, second) if r.status is Status.RETRY_LATER)
    assert retry.latency_ms is None


async def test_cancelled_batch_releases_capacity():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    task = asyncio.create_task(eng.process_batch([Item("a", {"text": "a"})]))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await eng.process(Item("b", {"text": "b"}))
    assert result.status is Status.DECIDED


def test_invalid_concurrency_limit_is_rejected():
    with pytest.raises(ValueError, match="max_concurrency"):
        make_engine(max_concurrency=0)


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


async def test_proposer_receives_known_labels_from_taxonomy():
    # a proposer should be able to reuse the official vocabulary instead of
    # inventing synonyms, so the engine hands it the taxonomy's known labels.
    taxonomy = InMemoryTaxonomyStore()
    await taxonomy.promote("food")
    proposer = _CapturingProposer()
    eng = Engine(
        context_builders=[_TextBuilder()],
        proposers=[proposer],
        scorers=[_FakeScorer()],
        policy=RecallBiasedPolicy(),
        sink=CollectingSink(),
        cache=InMemoryCache(),
        taxonomy=taxonomy,
        observer=InMemoryObserver(),
    )
    await eng.process(Item("i1", {"text": "x"}))
    assert proposer.seen_known_labels == {"food"}


async def test_decided_item_records_full_event():
    from labjury.audit import replay_decision, state_fingerprint, verdict_matches

    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    await eng.process(Item("i1", {"text": "x"}))
    [e] = await audit.by_correlation("i1")
    assert e.from_cache is False and e.used_proposer is True
    assert len(e.input_fingerprint) == 64  # fingerprint, not content
    assert e.candidates and e.answers
    assert "policy" in e.provenance and "scorer" in e.provenance
    assert e.provenance["policy"].params is not None
    assert e.known_labels == frozenset()  # fresh taxonomy
    assert e.verdict["action"] in ("accept", "review")
    state = State()
    state.add(Content("text", "x"))
    assert e.state_fingerprint == state_fingerprint(state)
    assert verdict_matches(
        e, await replay_decision(e, RecallBiasedPolicy(), state=state)
    )


async def test_cache_hit_records_thin_event():
    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    item = Item("i1", {"text": "x"})
    await eng.process(item)
    await eng.process(item)
    _, e = await audit.by_correlation("i1")
    assert e.from_cache is True and e.candidates == () and e.verdict["reason"] == "accepted"


async def test_review_is_rescored_and_audited_for_each_item():
    from labjury.review import review_task_from_event

    audit = InMemoryAuditLog()
    scorer = _ImageScorer(answer=Answer("nudity", value=True, confidence=0.95))
    eng = Engine(
        context_builders=[_ImageBuilder()],
        proposers=[],
        scorers=[scorer],
        policy=RecallBiasedPolicy(),
        sink=CollectingSink(),
        cache=InMemoryCache(),
        taxonomy=InMemoryTaxonomyStore(),
        observer=InMemoryObserver(),
        audit=audit,
        standing_candidates=[Candidate("nudity", "violation", NoulQuestion("nudity", "nudity?"))],
    )
    for cid in ("first", "second"):
        result = await eng.process(Item(cid, {"image": b"same"}))
        assert result.status is Status.REVIEW
        [event] = await audit.by_correlation(cid)
        task = review_task_from_event(event, content_ref=f"items/{cid}")
        assert event.from_cache is False
        assert task.candidates and task.answers
    assert scorer.calls == 2


async def test_existing_cached_review_is_ignored():
    class OldReviewCache(InMemoryCache):
        async def get(self, key):
            return Verdict(Action.REVIEW, [], {}, [], "old review")

    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    eng.cache = OldReviewCache()
    result = await eng.process(Item("i1", {"text": "food"}))
    [event] = await audit.by_correlation("i1")
    assert result.verdict.reason == "accepted"
    assert event.from_cache is False and event.candidates and event.answers


async def test_audit_failure_does_not_break_process():
    class Boom:
        async def record(self, event):
            raise RuntimeError("down")

        async def by_correlation(self, cid):
            return []

    eng = make_engine(audit=Boom())
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.status in (Status.DECIDED, Status.REVIEW)


def test_recall_biased_policy_exposes_params():
    from labjury.policies import RecallBiasedPolicy

    assert RecallBiasedPolicy().params == {"accept_threshold": 0.85, "clean_threshold": 0.9}


async def test_processed_item_records_latency():
    eng = make_engine()
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.latency_ms is not None and r.latency_ms >= 0.0


async def test_failed_item_still_records_latency():
    eng = make_engine(fail_on_id="i1")
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.status is Status.FAILED and r.latency_ms is not None


async def test_pre_admission_retry_later_has_no_latency():
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    results = await eng.process_batch([Item(f"i{n}", {"text": "t"}) for n in range(4)])
    retry = [r for r in results if r.status is Status.RETRY_LATER]
    assert retry and all(r.latency_ms is None for r in retry)


async def test_tenant_flows_to_result_and_audit():
    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    result = await eng.process(Item("i1", {"text": "x"}, tenant="acme"))
    assert result.tenant == "acme"
    events = await audit.by_correlation("i1")
    assert events and events[0].tenant == "acme"


async def test_cache_isolated_by_tenant_and_taxonomy():
    eng, proposer = make_engine(track_proposer=True)
    acme = Item("a", {"text": "same"}, tenant="acme")
    other = Item("b", {"text": "same"}, tenant="other")
    await eng.process(acme)
    await eng.process(other)
    assert proposer.calls == 2
    assert eng._key(acme) != eng._key(other)


async def test_cache_invalidated_by_taxonomy_change():
    audit = InMemoryAuditLog()
    eng = make_engine(audit=audit)
    item = Item("i1", {"text": "x"})
    await eng.process(item)
    await eng._taxonomy.promote("food")
    await eng.process(item)
    first, second = await audit.by_correlation("i1")
    assert second.from_cache is False
    assert first.input_fingerprint != second.input_fingerprint


async def test_cache_invalidated_by_rubric_change():
    class ChangingProposer(_FoodProposer):
        version = "v1"

        async def propose(self, state, context):
            self.calls += 1
            return [
                Candidate(
                    "food", "tag", ChoiceQuestion("food_q", "food?", ["food"]),
                    rubric_version=self.version,
                )
            ]

    proposer = ChangingProposer()
    audit = InMemoryAuditLog()
    taxonomy = InMemoryTaxonomyStore()
    await taxonomy.promote("food")
    eng = Engine(
        context_builders=[_TextBuilder()],
        proposers=[proposer],
        scorers=[_FakeScorer()],
        policy=RecallBiasedPolicy(),
        sink=CollectingSink(),
        cache=InMemoryCache(),
        taxonomy=taxonomy,
        observer=InMemoryObserver(),
        audit=audit,
    )
    item = Item("i1", {"text": "x"})
    await eng.process(item)
    proposer.version = "v2"
    await eng.process(item)
    first, second = await audit.by_correlation("i1")
    assert second.from_cache is False
    assert first.input_fingerprint != second.input_fingerprint
