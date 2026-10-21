from labjury import Content, Scorer, State
import pytest

from labjury.decisions import ChoiceQuestion, NoulQuestion, ScoreQuestion
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


async def test_prompt_contains_text_being_judged():
    prompts = []

    async def fake_chat(prompt: str) -> str:
        prompts.append(prompt)
        return '{"value": true, "confidence": 0.95}'

    state = State()
    state.add(Content("text", "món ăn ngon"))
    await LLMJudgeScorer(chat=fake_chat).score(state, [NoulQuestion("food", "food?")])
    assert "món ăn ngon" in prompts[0]
    assert "food?" in prompts[0]


@pytest.mark.parametrize(
    ("question", "response"),
    [
        (NoulQuestion("yes", "yes?"), '{"value": "true", "confidence": 0.9}'),
        (ChoiceQuestion("topic", "topic?", ["food", "tech"]), '{"value": "other", "confidence": 0.9}'),
        (ScoreQuestion("quality", "quality?", ["low", "high"]), '{"value": "medium", "confidence": 0.9}'),
        (NoulQuestion("yes", "yes?"), '{"value": true, "confidence": true}'),
        (NoulQuestion("yes", "yes?"), '{"value": true, "confidence": 1.2}'),
        (NoulQuestion("yes", "yes?"), '[]'),
    ],
)
async def test_rejects_invalid_model_answer(question, response):
    async def fake_chat(prompt: str) -> str:
        return response

    with pytest.raises(ValueError):
        await LLMJudgeScorer(chat=fake_chat).score(State(), [question])


async def test_accepts_score_level():
    async def fake_chat(prompt: str) -> str:
        return '{"value": "high", "confidence": 0.8}'

    answers = await LLMJudgeScorer(chat=fake_chat).score(
        State(), [ScoreQuestion("quality", "quality?", ["low", "high"])]
    )
    assert answers[0].value == "high"
