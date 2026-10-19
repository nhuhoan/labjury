from labjury import Scorer, State
from labjury.decisions import ChoiceQuestion, NoulQuestion
from labjury.scorers.llm_judge import LLMJudgeScorer


async def test_scores_each_question_type_via_injected_chat():
    async def fake_chat(prompt: str) -> str:
        if "promotes alcohol" in prompt:
            return '{"value": true, "confidence": 0.92}'
        return '{"value": "food", "confidence": 0.8}'

    scorer = LLMJudgeScorer(chat=fake_chat)
    qs = [
        NoulQuestion("alcohol", "promotes alcohol?"),
        ChoiceQuestion("t", "topic?", ["food", "tech"]),
    ]
    answers = await scorer.score(State(), qs)
    by_key = {a.key: a for a in answers}
    assert by_key["alcohol"].value is True and by_key["alcohol"].confidence == 0.92
    assert by_key["t"].value == "food"


async def test_satisfies_scorer_protocol_and_needs_no_jev():
    async def fake_chat(prompt: str) -> str:
        return '{"value": false, "confidence": 0.5}'

    scorer = LLMJudgeScorer(chat=fake_chat)
    assert isinstance(scorer, Scorer)
    answers = await scorer.score(State(), [NoulQuestion("x", "x?")])
    assert answers[0].value is False and answers[0].key == "x"
