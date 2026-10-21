import pytest

from labjury.plugins import Proposer, ProposalContext, Redactor, Scorer
from labjury.decisions import NoulQuestion
from labjury.redaction import (
    RedactingProposer,
    RedactingScorer,
    RegexRedactor,
    UnredactedModalityError,
)
from labjury.state import Content, State
from labjury.scorers.llm_judge import LLMJudgeScorer


class _RecordingScorer:
    accepts = frozenset({"*"})

    def __init__(self) -> None:
        self.seen = None

    async def score(self, state, questions):
        self.seen = state
        return []


class _RecordingProposer:
    accepts = frozenset({"*"})

    def __init__(self) -> None:
        self.seen = None

    async def propose(self, state, context):
        self.seen = state
        return []


class _FakeRedactor:
    def __init__(self, accepts=frozenset({"text"})) -> None:
        self.accepts = accepts

    async def redact(self, state: State) -> State:
        out = State()
        out.flags = set(state.flags)
        for mod in state.modalities():
            for c in state.get(mod):
                if c.modality == "text":
                    out.add(Content("text", c.payload.upper(), c.meta))
                else:
                    out.add(c)
        return out


class _RaisingRedactor:
    accepts = frozenset({"text"})

    async def redact(self, state: State) -> State:
        raise RuntimeError("boom")


async def test_redacting_scorer_passes_redacted_state_to_inner():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    out = await RedactingScorer(inner, _FakeRedactor()).score(s, [])
    assert inner.seen.get("text")[0].payload == "HI"
    assert out == []


async def test_original_state_unchanged():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    await RedactingScorer(inner, _FakeRedactor()).score(s, [])
    assert s.get("text")[0].payload == "hi"  # original untouched
    assert inner.seen is not s  # inner saw a copy


async def test_redactor_error_propagates_without_calling_inner():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    with pytest.raises(RuntimeError):
        await RedactingScorer(inner, _RaisingRedactor()).score(s, [])
    assert inner.seen is None  # fail-closed


async def test_strict_blocks_uncovered_modality():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    s.add(Content("image", b"x"))
    with pytest.raises(UnredactedModalityError):
        await RedactingScorer(inner, _FakeRedactor()).score(s, [])  # strict default
    assert inner.seen is None


async def test_non_strict_allows_uncovered_modality():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("text", "hi"))
    s.add(Content("image", b"x"))
    await RedactingScorer(inner, _FakeRedactor(), strict=False).score(s, [])
    assert inner.seen is not None  # inner was called


async def test_star_redactor_covers_everything_in_strict():
    inner = _RecordingScorer()
    s = State()
    s.add(Content("image", b"x"))
    await RedactingScorer(inner, _FakeRedactor(accepts=frozenset({"*"}))).score(s, [])
    assert inner.seen is not None


def test_redacting_scorer_is_a_scorer():
    assert isinstance(RedactingScorer(_RecordingScorer(), _FakeRedactor()), Scorer)


async def test_redacting_proposer_redacts_and_is_a_proposer():
    inner = _RecordingProposer()
    s = State()
    s.add(Content("text", "hi"))
    await RedactingProposer(inner, _FakeRedactor()).propose(s, ProposalContext())
    assert inner.seen.get("text")[0].payload == "HI"
    assert isinstance(RedactingProposer(inner, _FakeRedactor()), Proposer)


async def test_regex_masks_email_phone_card():
    s = State()
    s.add(Content("text", "mail a@b.com call 0912345678 card 4111 1111 1111 1111"))
    out = await RegexRedactor().redact(s)
    masked = out.get("text")[0].payload
    assert "a@b.com" not in masked and "[EMAIL]" in masked
    assert "[PHONE]" in masked and "[CARD]" in masked


async def test_regex_leaves_non_text_untouched():
    s = State()
    s.add(Content("image", b"rawbytes"))
    out = await RegexRedactor().redact(s)
    assert out.get("image")[0].payload == b"rawbytes"


async def test_regex_returns_new_state_original_unchanged():
    s = State()
    s.add(Content("text", "a@b.com"))
    await RegexRedactor().redact(s)
    assert s.get("text")[0].payload == "a@b.com"


def test_regex_redactor_is_a_redactor():
    assert isinstance(RegexRedactor(), Redactor)


async def test_text_metadata_is_masked_before_llm_prompt():
    prompts = []

    async def chat(prompt):
        prompts.append(prompt)
        return '{"value": true, "confidence": 0.95}'

    state = State()
    state.add(Content("text", "hello", {"contact": ["a@b.com", {"0912345678": "call"}]}))
    await RedactingScorer(LLMJudgeScorer(chat), RegexRedactor()).score(
        state, [NoulQuestion("q", "food?")]
    )
    assert "a@b.com" not in prompts[0] and "0912345678" not in prompts[0]
    assert "[EMAIL]" in prompts[0] and "[PHONE]" in prompts[0]
    assert state.get("text")[0].meta["contact"][0] == "a@b.com"
