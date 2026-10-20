"""Plugin protocols with capability declarations.

The framework ↔ plugin boundary is a Python async interface, not a network
protocol (§6.4): the core never knows whether a plugin is backed by HTTP,
gRPC, or a local model. Each stage plugin declares ``accepts`` — the set of
modalities it consumes; ``frozenset({"*"})`` means "any".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from labjury.decisions import Answer, Candidate, Question
from labjury.results import ItemResult, Verdict
from labjury.state import Item, State


@dataclass(frozen=True)
class ProposalContext:
    """Read-only context handed to a :class:`Proposer` for one item.

    A single extensible container so the core can give proposers more to work
    with over time (locale, budget, …) *without* changing the ``propose``
    signature and breaking third-party plugins. ``known_labels`` is the
    taxonomy's official vocabulary, offered so a proposer can reuse an
    existing label instead of inventing a near-duplicate. It is a
    ``frozenset`` by design: proposers read the vocabulary, they never mutate
    it — writing to the taxonomy stays solely with the decision policy.
    """

    known_labels: frozenset[str] = field(default_factory=frozenset)


@runtime_checkable
class ContextBuilder(Protocol):
    accepts: frozenset[str]
    produces: frozenset[str]

    async def build(self, item: Item, state: State) -> State: ...


@runtime_checkable
class Proposer(Protocol):
    accepts: frozenset[str]

    async def propose(
        self, state: State, context: ProposalContext
    ) -> list[Candidate]: ...


@runtime_checkable
class Scorer(Protocol):
    accepts: frozenset[str]

    async def score(self, state: State, questions: list[Question]) -> list[Answer]: ...


@runtime_checkable
class TaxonomyStore(Protocol):
    async def is_known(self, label: str) -> bool: ...

    async def propose(self, label: str, meta: dict | None = None) -> None: ...

    async def promote(self, label: str) -> None: ...

    async def known_labels(self) -> set[str]: ...

    async def proposed_labels(self) -> set[str]: ...


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
