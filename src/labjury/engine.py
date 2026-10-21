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
import time
import uuid
from typing import Callable

from labjury.audit import (
    AuditEvent,
    answer_to_dict,
    candidate_to_dict,
    provenance_of,
    state_fingerprint,
    verdict_to_dict,
)
from labjury.decisions import Candidate
from labjury.defaults import NullAuditLog
from labjury.plugins import (
    AuditLog,
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
from labjury.results import Action, ItemResult, Status
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
        audit: AuditLog | None = None,
        standing_candidates: list[Candidate] | None = None,
        max_concurrency: int = 64,
        cache_key: Callable[[Item], str] | None = None,
        cache_namespace: str | None = None,
    ) -> None:
        self._context_builders = context_builders
        self._proposers = proposers
        self._scorers = scorers
        self._policy = policy
        self.cache = cache
        self._sink = sink
        self._taxonomy = taxonomy
        self._observer = observer
        self._audit = audit or NullAuditLog()
        self._standing = standing_candidates or []
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency = max_concurrency
        self._in_flight = 0
        self._cache_key = cache_key or self._default_key
        self._cache_namespace = (
            cache_namespace if cache_namespace is not None else uuid.uuid4().hex
        )
        self._router = Router(proposers, scorers)

    # -- public API ---------------------------------------------------------

    async def process(self, item: Item) -> ItemResult:
        if self._in_flight >= self._max_concurrency:
            result = ItemResult(item.id, Status.RETRY_LATER, tenant=item.tenant)
            await self._finish(result)
            return result

        self._in_flight += 1
        return await self._process_reserved(item)

    async def _process_reserved(self, item: Item) -> ItemResult:
        start = time.perf_counter()
        try:
            try:
                result = await self._run(item)
            except Exception as exc:  # partial-failure: never let one item escape
                result = ItemResult(item.id, Status.FAILED, error=str(exc))
            result.latency_ms = (time.perf_counter() - start) * 1000.0
            result.tenant = item.tenant
            await self._finish(result)
            return result
        finally:
            self._in_flight -= 1

    async def process_batch(self, items: list[Item]) -> list[ItemResult]:
        available = max(0, self._max_concurrency - self._in_flight)
        admitted = items[:available]
        results: list[ItemResult] = []
        for item in items[available:]:
            results.append(ItemResult(item.id, Status.RETRY_LATER, tenant=item.tenant))
        done = await asyncio.gather(
            *(self.process(i) for i in admitted), return_exceptions=True
        )
        for result in results:
            self._observer.on_retry_later(result)
        for item, outcome in zip(admitted, done):
            if isinstance(outcome, BaseException):
                results.append(
                    ItemResult(
                        item.id, Status.FAILED, error=str(outcome), tenant=item.tenant
                    )
                )
            else:
                results.append(outcome)
        return results

    def _key(self, item: Item) -> str:
        return self._cache_key(item)

    def _decision_key(
        self,
        item: Item,
        state: State,
        known: frozenset[str],
        candidates: list[Candidate],
        scorer: Scorer,
    ) -> str:
        content = [
            {"modality": modality, "payload": piece.payload, "meta": piece.meta}
            for modality in sorted(state.modalities())
            for piece in state.get(modality)
        ]
        context = {
            "schema": 3,
            "namespace": self._cache_namespace,
            "item_key": self._key(item),
            "tenant": item.tenant,
            "meta": item.meta,
            "content": content,
            "flags": sorted(state.flags),
            "known_labels": sorted(known),
            "candidates": [candidate_to_dict(c) for c in candidates],
            "scorer": provenance_of(scorer).to_dict(),
            "policy": provenance_of(self._policy).to_dict(),
        }
        return hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()

    # -- internals ----------------------------------------------------------

    async def _run(self, item: Item) -> ItemResult:
        state = State()
        for builder in self._context_builders:
            state = await builder.build(item, state)

        known = frozenset(await self._taxonomy.known_labels())
        route = self._router.route(state)
        if route.use_proposer:
            context = ProposalContext(known)
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

        key = self._decision_key(item, state, known, candidates, route.scorer)
        cached = await self.cache.get(key)
        if cached is not None and cached.action is not Action.REVIEW:
            for label in cached.novel_labels:
                await self._taxonomy.propose(label)
            await self._record_safe(
                AuditEvent(
                    item.id,
                    key,
                    from_cache=True,
                    verdict=verdict_to_dict(cached),
                    tenant=item.tenant,
                )
            )
            return ItemResult(item.id, self._status_for(cached.action), verdict=cached)

        questions = [c.question for c in candidates]
        answers = await route.scorer.score(state, questions) if questions else []
        policy_state_fingerprint = state_fingerprint(state)
        verdict = await self._policy.decide(state, candidates, answers, self._taxonomy)
        if verdict.action is not Action.REVIEW:
            await self.cache.put(key, verdict)
        await self._record_safe(
            AuditEvent(
                item.id,
                key,
                modalities=frozenset(state.modalities()),
                used_proposer=route.use_proposer,
                candidates=tuple(candidate_to_dict(c) for c in candidates),
                answers=tuple(answer_to_dict(a) for a in answers),
                known_labels=known,
                provenance={
                    "scorer": provenance_of(route.scorer),
                    "policy": provenance_of(self._policy),
                },
                verdict=verdict_to_dict(verdict),
                tenant=item.tenant,
                state_fingerprint=policy_state_fingerprint,
            )
        )
        return ItemResult(item.id, self._status_for(verdict.action), verdict=verdict)

    async def _record_safe(self, event: AuditEvent) -> None:
        # Auditing is a side record; a failing backend must never break a
        # decision. Swallow here — the backend owns its own durability/retry.
        try:
            await self._audit.record(event)
        except Exception:  # noqa: BLE001 - best-effort audit, never fatal
            pass

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
        blob = json.dumps(
            {"raw": item.raw, "meta": item.meta, "tenant": item.tenant},
            sort_keys=True,
            default=str,
        ).encode()
        return hashlib.sha256(blob).hexdigest()
