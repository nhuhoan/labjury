"""The async decision engine.

Owns fast-processing *mechanisms* — async flow, batching, bounded
concurrency, explicit backpressure, caching — but no queue, storage, or
scale. It is driven by an external worker calling :meth:`process` /
:meth:`process_batch`.

``process_batch`` contract: results are **unordered** (each carries its
item's correlation id), **partial-failure-tolerant** (one bad item yields a
``FAILED`` result, siblings unaffected), and backpressure is **explicit**
(items beyond ``max_concurrency`` in a call return ``RETRY_LATER`` rather
than blocking, so the caller re-enqueues).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Callable

from labjury.decisions import Candidate
from labjury.plugins import (
    Cache,
    ContextBuilder,
    DecisionPolicy,
    Proposer,
    ProposalContext,
    Scorer,
    Sink,
    TaxonomyStore,
)
from labjury.observability import Observer
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.router import Router
from labjury.state import Item, State


class Engine:
    def __init__(
        self,
        context_builders: list[ContextBuilder],
        proposers: list[Proposer],
        scorers: list[Scorer],
        policy: DecisionPolicy,
        sink: Sink,
        cache: Cache,
        taxonomy: TaxonomyStore,
        observer: Observer,
        *,
        standing_candidates: list[Candidate] | None = None,
        max_concurrency: int = 64,
        cache_key: Callable[[Item], str] | None = None,
    ) -> None:
        self._context_builders = context_builders
        self._proposers = proposers
        self._scorers = scorers
        self._policy = policy
        self.cache = cache
        self._sink = sink
        self._taxonomy = taxonomy
        self._observer = observer
        self._standing = standing_candidates or []
        self._max_concurrency = max_concurrency
        self._cache_key = cache_key or self._default_key
        self._router = Router(proposers, scorers)

    # -- public API ---------------------------------------------------------

    async def process(self, item: Item) -> ItemResult:
        try:
            result = await self._run(item)
        except Exception as exc:  # partial-failure: never let one item escape
            result = ItemResult(item.id, Status.FAILED, error=str(exc))
        await self._finish(result)
        return result

    async def process_batch(self, items: list[Item]) -> list[ItemResult]:
        admitted: list[Item] = []
        results: list[ItemResult] = []
        for item in items:
            if len(admitted) < self._max_concurrency:
                admitted.append(item)
            else:
                rl = ItemResult(item.id, Status.RETRY_LATER)
                self._observer.on_retry_later(rl)
                results.append(rl)
        done = await asyncio.gather(
            *(self.process(i) for i in admitted), return_exceptions=True
        )
        for item, outcome in zip(admitted, done):
            if isinstance(outcome, BaseException):
                results.append(ItemResult(item.id, Status.FAILED, error=str(outcome)))
            else:
                results.append(outcome)
        return results

    def _key(self, item: Item) -> str:
        return self._cache_key(item)

    # -- internals ----------------------------------------------------------

    async def _run(self, item: Item) -> ItemResult:
        key = self._cache_key(item)
        cached = await self.cache.get(key)
        if cached is not None:
            return ItemResult(item.id, self._status_for(cached.action), verdict=cached)

        state = State()
        for builder in self._context_builders:
            state = await builder.build(item, state)

        route = self._router.route(state)
        if route.use_proposer:
            context = ProposalContext(frozenset(await self._taxonomy.known_labels()))
            candidates = list(self._standing)
            for proposer in self._proposers:
                if "*" in proposer.accepts or state.modalities() <= set(proposer.accepts):
                    candidates.extend(await proposer.propose(state, context))
        else:
            candidates = list(self._standing)
            if not candidates:
                return ItemResult(
                    item.id, Status.FAILED, error="no candidates on fast path"
                )

        questions = [c.question for c in candidates]
        answers = await route.scorer.score(state, questions)
        verdict = await self._policy.decide(state, candidates, answers, self._taxonomy)
        await self.cache.put(key, verdict)
        return ItemResult(item.id, self._status_for(verdict.action), verdict=verdict)

    async def _finish(self, result: ItemResult) -> None:
        await self._sink.emit(result)
        if result.status is Status.DECIDED:
            self._observer.on_decided(result)
        elif result.status is Status.REVIEW:
            self._observer.on_review(result)
        elif result.status is Status.FAILED:
            self._observer.on_failed(result)
        elif result.status is Status.RETRY_LATER:
            self._observer.on_retry_later(result)

    @staticmethod
    def _status_for(action: Action) -> Status:
        return Status.REVIEW if action is Action.REVIEW else Status.DECIDED

    @staticmethod
    def _default_key(item: Item) -> str:
        blob = json.dumps(item.raw, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()
