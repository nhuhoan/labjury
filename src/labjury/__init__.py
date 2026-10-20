"""LabJury — a plugin-driven, async decision engine for labeling and moderation.

Proposers plead, a scorer judges, a verdict is rendered. Runs without Jev via
the built-in :class:`LLMJudgeScorer` fallback.
"""

from labjury.decisions import (
    Answer,
    Candidate,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
)
from labjury.defaults import CollectingSink, InMemoryCache
from labjury.engine import Engine
from labjury.observability import InMemoryObserver, Observer
from labjury.plugins import (
    Cache,
    ContextBuilder,
    DecisionPolicy,
    ProposalContext,
    Proposer,
    Scorer,
    Sink,
    TaxonomyStore,
)
from labjury.policies import RecallBiasedPolicy
from labjury.registry import available, clear, get, load_entry_points, register
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.router import NoRouteError, Route, Router
from labjury.scorers.llm_judge import LLMJudgeScorer
from labjury.state import (
    Content,
    Item,
    State,
    is_content_type,
    register_content_type,
)
from labjury.taxonomy import InMemoryTaxonomyStore
from labjury.testing import assert_taxonomy_store_contract

__all__ = [
    # state
    "Content",
    "Item",
    "State",
    "is_content_type",
    "register_content_type",
    # decisions
    "ChoiceQuestion",
    "ScoreQuestion",
    "NoulQuestion",
    "Question",
    "Answer",
    "Candidate",
    # results
    "Action",
    "Status",
    "Verdict",
    "ItemResult",
    # plugin protocols
    "ContextBuilder",
    "Proposer",
    "ProposalContext",
    "Scorer",
    "DecisionPolicy",
    "Sink",
    "TaxonomyStore",
    "Cache",
    "Observer",
    # registry
    "register",
    "get",
    "available",
    "clear",
    "load_entry_points",
    # routing + engine
    "Router",
    "Route",
    "NoRouteError",
    "Engine",
    # default/built-in plugins
    "RecallBiasedPolicy",
    "InMemoryTaxonomyStore",
    "InMemoryCache",
    "CollectingSink",
    "InMemoryObserver",
    "LLMJudgeScorer",
    # testing helpers
    "assert_taxonomy_store_contract",
]
