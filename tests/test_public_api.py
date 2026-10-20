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


# The curated load-bearing public names: dropping any of these from __all__ is a
# major-version break, so the suite guards them explicitly.
_MUST_REMAIN_PUBLIC = {
    "Engine", "Item", "State", "Content",
    "ContextBuilder", "Proposer", "Scorer", "DecisionPolicy", "Sink", "Cache",
    "Observer", "TaxonomyStore", "AuditLog",
    "register", "get", "available", "load_entry_points",
    "__version__",
}

# Exported plugin protocols must stay runtime-checkable so authors can isinstance.
_EXPORTED_PROTOCOLS = [
    "ContextBuilder", "Proposer", "Scorer", "DecisionPolicy", "Sink", "Cache",
    "Observer", "TaxonomyStore", "AuditLog", "RubricStore", "Redactor", "Guard",
    "ReviewQueue",
]


def test_public_surface_importable():
    # __all__ *is* the public contract: every name in it must resolve.
    for name in lj.__all__:
        assert hasattr(lj, name), f"{name} in __all__ but not importable"


def test_core_names_remain_public():
    missing = _MUST_REMAIN_PUBLIC - set(lj.__all__)
    assert not missing, f"core public names dropped from __all__: {missing}"


def test_exported_protocols_are_runtime_checkable():
    for name in _EXPORTED_PROTOCOLS:
        proto = getattr(lj, name)
        assert getattr(proto, "_is_runtime_protocol", False), (
            f"{name} must be @runtime_checkable so plugin authors can isinstance-check"
        )


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
