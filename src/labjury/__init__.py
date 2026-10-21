"""LabJury — a plugin-driven, async decision engine for labeling and moderation.

Proposers plead, a scorer judges, a verdict is rendered. Runs without Jev via
the built-in :class:`LLMJudgeScorer` fallback.
"""

__version__ = "0.0.1"

from labjury.decisions import (
    Answer,
    Candidate,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
)
from labjury.defaults import (
    CollectingSink,
    InMemoryAuditLog,
    InMemoryCache,
    NullAuditLog,
)
from labjury.engine import Engine
from labjury.observability import (
    FanOutObserver,
    InMemoryObserver,
    Observer,
    PerTenantUsage,
    TenantUsage,
)
from labjury.plugins import (
    AuditLog,
    Cache,
    ContextBuilder,
    DecisionPolicy,
    Guard,
    ProposalContext,
    Proposer,
    Redactor,
    ReviewQueue,
    RubricStore,
    Scorer,
    Sink,
    TaxonomyStore,
)
from labjury.redaction import (
    RedactingProposer,
    RedactingScorer,
    RegexRedactor,
    UnredactedModalityError,
)
from labjury.guards import (
    GuardRejected,
    GuardedProposer,
    GuardedScorer,
    HeuristicInjectionGuard,
)
from labjury.secrets import Secret
from labjury.rubrics import InMemoryRubricStore, Rubric
from labjury.evaluation import (
    EvalComparison,
    EvalReport,
    GoldenCase,
    LabelScore,
    compare_evals,
    run_evaluation,
    score_predictions,
)
from labjury.review import (
    InMemoryReviewQueue,
    ReviewResolution,
    ReviewTask,
    review_task_from_event,
)
from labjury.audit import (
    AuditEvent,
    ProvenanceRef,
    ReplayReport,
    RubricDrift,
    VersionChange,
    replay_decision,
    rubric_drift,
    verdict_matches,
    verify_replay,
)
from labjury.policies import RecallBiasedPolicy
from labjury.reliability import (
    CircuitOpenError,
    FailoverContextBuilder,
    FailoverProposer,
    FailoverScorer,
    ReliableContextBuilder,
    ReliableProposer,
    ReliableScorer,
)
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
from labjury.testing import (
    assert_audit_log_contract,
    assert_plugin_conforms,
    assert_rubric_store_contract,
    assert_taxonomy_store_contract,
)

__all__ = [
    # meta
    "__version__",
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
    "AuditLog",
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
    # audit
    "AuditEvent",
    "ProvenanceRef",
    "NullAuditLog",
    "InMemoryAuditLog",
    "replay_decision",
    "verdict_matches",
    "verify_replay",
    "ReplayReport",
    "VersionChange",
    "rubric_drift",
    "RubricDrift",
    # testing helpers
    "assert_taxonomy_store_contract",
    "assert_audit_log_contract",
    "assert_plugin_conforms",
    # remote-plugin reliability
    "ReliableScorer",
    "ReliableProposer",
    "ReliableContextBuilder",
    "CircuitOpenError",
    "FailoverScorer",
    "FailoverProposer",
    "FailoverContextBuilder",
    # pii redaction
    "Redactor",
    "RedactingScorer",
    "RedactingProposer",
    "RegexRedactor",
    "UnredactedModalityError",
    # prompt-injection guards
    "Guard",
    "GuardedScorer",
    "GuardedProposer",
    "HeuristicInjectionGuard",
    "GuardRejected",
    # secrets
    "Secret",
    # rubric registry
    "Rubric",
    "RubricStore",
    "InMemoryRubricStore",
    "assert_rubric_store_contract",
    # multi-tenancy & per-tenant cost
    "TenantUsage",
    "PerTenantUsage",
    "FanOutObserver",
    # human review
    "ReviewTask",
    "ReviewResolution",
    "ReviewQueue",
    "InMemoryReviewQueue",
    "review_task_from_event",
    # evaluation
    "LabelScore",
    "EvalReport",
    "score_predictions",
    "GoldenCase",
    "run_evaluation",
    "EvalComparison",
    "compare_evals",
]
