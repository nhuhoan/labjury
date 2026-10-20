import labjury as lj
from labjury import Candidate, ChoiceQuestion, Content


class _TextBuilder:
    accepts = frozenset({"*"})
    produces = frozenset({"text"})

    async def build(self, item, state):
        state.add(Content("text", item.raw["text"]))
        return state


class _FoodProposer:
    accepts = frozenset({"*"})

    async def propose(self, state, context):
        return [Candidate("food", "tag", ChoiceQuestion("food_q", "food?", ["food"]))]


def test_public_surface_importable():
    for name in [
        "Engine",
        "Item",
        "State",
        "LLMJudgeScorer",
        "RecallBiasedPolicy",
        "InMemoryCache",
        "InMemoryTaxonomyStore",
        "CollectingSink",
        "InMemoryObserver",
        "Router",
        "Proposer",
        "ProposalContext",
        "ReliableScorer",
        "ReliableProposer",
        "ReliableContextBuilder",
        "CircuitOpenError",
        "Redactor",
        "RedactingScorer",
        "RedactingProposer",
        "RegexRedactor",
        "UnredactedModalityError",
        "Guard",
        "GuardedScorer",
        "GuardedProposer",
        "HeuristicInjectionGuard",
        "GuardRejected",
        "Secret",
        "Rubric",
        "RubricStore",
        "InMemoryRubricStore",
        "assert_rubric_store_contract",
        "register",
        "load_entry_points",
    ]:
        assert hasattr(lj, name), f"missing public export: {name}"


async def test_full_pipeline_runs_without_jev():
    async def chat(prompt: str) -> str:
        return '{"value": "food", "confidence": 0.95}'

    eng = lj.Engine(
        context_builders=[_TextBuilder()],
        proposers=[_FoodProposer()],
        scorers=[lj.LLMJudgeScorer(chat=chat)],
        policy=lj.RecallBiasedPolicy(),
        sink=lj.CollectingSink(),
        cache=lj.InMemoryCache(),
        taxonomy=lj.InMemoryTaxonomyStore(),
        observer=lj.InMemoryObserver(),
    )
    r = await eng.process(lj.Item("i1", {"text": "món ăn ngon"}))
    assert r.status in (lj.Status.DECIDED, lj.Status.REVIEW)
