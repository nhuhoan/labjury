"""Plugin protocols with capability declarations.

The framework ↔ plugin boundary is a Python async interface, not a network
protocol (§6.4): the core never knows whether a plugin is backed by HTTP,
gRPC, or a local model. Each stage plugin declares ``accepts`` — the set of
modalities it consumes; ``frozenset({"*"})`` means "any".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from labjury.decisions import Answer, Candidate, Question
from labjury.results import ItemResult, Verdict
from labjury.state import Item, State


@runtime_checkable
class ContextBuilder(Protocol):
    accepts: frozenset[str]
    produces: frozenset[str]

    async def build(self, item: Item, state: State) -> State: ...


@runtime_checkable
class Proposer(Protocol):
    accepts: frozenset[str]

    async def propose(self, state: State) -> list[Candidate]: ...


@runtime_checkable
class Scorer(Protocol):
    accepts: frozenset[str]

    async def score(self, state: State, questions: list[Question]) -> list[Answer]: ...


@runtime_checkable
class TaxonomyStore(Protocol):
    async def is_known(self, label: str) -> bool: ...

    async def propose(self, label: str, meta: dict | None = None) -> None: ...

    async def known_labels(self) -> set[str]: ...


@runtime_checkable
class DecisionPolicy(Protocol):
    async def decide(
        self,
        state: State,
        candidates: list[Candidate],
        answers: list[Answer],
        taxonomy: TaxonomyStore,
    ) -> Verdict: ...


@runtime_checkable
class Sink(Protocol):
    async def emit(self, result: ItemResult) -> None: ...


@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> Verdict | None: ...

    async def put(self, key: str, verdict: Verdict) -> None: ...
