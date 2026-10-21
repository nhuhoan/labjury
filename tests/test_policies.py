from labjury import (
    Action,
    Candidate,
    ChoiceQuestion,
    NoulQuestion,
    ScoreQuestion,
    State,
)
from labjury.decisions import Answer
from labjury.policies import RecallBiasedPolicy
from labjury.taxonomy import InMemoryTaxonomyStore


async def tax_seed(tax, labels):
    for label in labels:
        await tax.propose(label)
        await tax.promote(label)


async def test_unsure_violation_is_held():
    cands = [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))]
    answers = [Answer("alcohol", value=False, confidence=0.4)]  # unsure it's clean
    v = await RecallBiasedPolicy().decide(State(), cands, answers, InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW


async def test_confidently_clean_violation_passes():
    answers = [Answer("alcohol", value=False, confidence=0.97)]
    v = await RecallBiasedPolicy().decide(
        State(),
        [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))],
        answers,
        InMemoryTaxonomyStore(),
    )
    assert v.action is Action.ACCEPT


async def test_confident_violation_is_held():
    answers = [Answer("alcohol", value=True, confidence=0.95)]
    v = await RecallBiasedPolicy().decide(
        State(),
        [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))],
        answers,
        InMemoryTaxonomyStore(),
    )
    assert v.action is Action.REVIEW  # not confidently clean -> held


async def test_novel_label_proposed_and_flagged():
    tax = InMemoryTaxonomyStore()
    await tax_seed(tax, {"food"})
    cands = [Candidate("mukbang", "tag", ChoiceQuestion("t", "?", ["mukbang"]))]
    answers = [Answer("t", value="mukbang", confidence=0.95)]
    v = await RecallBiasedPolicy().decide(State(), cands, answers, tax)
    assert "mukbang" in v.novel_labels and await tax.is_known("mukbang") is False


async def test_known_label_is_not_novel():
    tax = InMemoryTaxonomyStore()
    await tax_seed(tax, {"food"})
    cands = [Candidate("food", "tag", ChoiceQuestion("t", "?", ["food"]))]
    answers = [Answer("t", value="food", confidence=0.95)]
    v = await RecallBiasedPolicy().decide(State(), cands, answers, tax)
    assert v.action is Action.ACCEPT and v.novel_labels == []


async def test_all_low_confidence_goes_to_review():
    cands = [Candidate("food", "tag", ChoiceQuestion("t", "?", ["food"]))]
    answers = [Answer("t", value="food", confidence=0.3)]
    v = await RecallBiasedPolicy().decide(State(), cands, answers, InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW


async def test_confident_wrong_choice_does_not_accept_label():
    tax = InMemoryTaxonomyStore()
    cands = [Candidate("food", "tag", ChoiceQuestion("t", "topic?", ["food", "not_food"]))]
    v = await RecallBiasedPolicy().decide(
        State(), cands, [Answer("t", value="not_food", confidence=0.95)], tax
    )
    assert v.action is Action.REVIEW and v.labels == []
    assert await tax.proposed_labels() == set()


async def test_boolean_label_needs_true_value():
    cands = [Candidate("food", "tag", NoulQuestion("food", "food?"))]
    v = await RecallBiasedPolicy().decide(
        State(), cands, [Answer("food", value=False, confidence=0.95)], InMemoryTaxonomyStore()
    )
    assert v.action is Action.REVIEW and v.labels == []


async def test_no_candidates_goes_to_review():
    v = await RecallBiasedPolicy().decide(State(), [], [], InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW and v.labels == []


async def test_score_question_accepts_only_highest_level():
    candidate = Candidate("quality", "tag", ScoreQuestion("q", "quality?", ["low", "high"]))
    tax = InMemoryTaxonomyStore()
    high = await RecallBiasedPolicy().decide(
        State(), [candidate], [Answer("q", "high", 0.95)], tax
    )
    low = await RecallBiasedPolicy().decide(
        State(), [candidate], [Answer("q", "low", 0.95)], tax
    )
    assert high.action is Action.ACCEPT and high.labels == ["quality"]
    assert low.action is Action.REVIEW and low.labels == []
