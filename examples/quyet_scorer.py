"""QuyetScorer — a reference ``Scorer`` for Quyet-1.0-Large (example, not shipped).

Quyet (FPT Cloud marketplace, ``chinhnc/quyet-1.0-large``, fine-tuned from
Gemma-4-31B-it) is a *calibrated decision model*: instead of generating text it
reads a state and a typed question and returns one option with calibrated
probabilities. That is, verbatim, the LabJury :class:`~labjury.plugins.Scorer`
contract — and Quyet's three question ``type``s (``choice`` / ``noul`` /
``score``) line up 1:1 with LabJury's ``ChoiceQuestion`` / ``NoulQuestion`` /
``ScoreQuestion``. So this adapter is **structure mapping, not semantic
translation**: a thin, honest bridge.

It lives in ``examples/`` on purpose. The framework ships the universal
``Scorer`` interface and one generic in-core scorer (``LLMJudgeScorer``, no
provider import); its product is the contract plus the pipeline, not per-vendor
glue. Bundling a vendor adapter into core would couple the framework to that
vendor's API churn. A real installable ``labjury-quyet`` package (vendor-owned
where possible) is the next step once there is install demand.

The HTTP ``transport`` is **injected**, so this module imports no third party and
is testable with a fake. The optional :func:`httpx_transport` factory is a
one-line turnkey path that imports ``httpx`` lazily.

Design: ``docs/superpowers/specs/2026-10-22-quyet-scorer-design.md``.
Wire contract (observed, authoritative): ``POST`` to
``https://mkp-api.fptcloud.com/v1/systemone``, ``Authorization: Bearer <key>``,
text-only input (``input_modalities: ["text"]``).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from labjury import (
    Answer,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
    State,
)

ENDPOINT = "https://mkp-api.fptcloud.com/v1/systemone"
DEFAULT_MODEL = "Quyet-1.0-Large"

# Transport owns HTTP + auth: it takes the request body and returns parsed JSON.
Transport = Callable[[dict], Awaitable[dict]]


class QuyetPartialFailure(Exception):
    """One or more questions came back unanswered (fail-closed).

    A *missing* judgment in a gating/labeling system must surface, never be
    fabricated as a low-confidence answer that then flows into block/hold. A
    deployer who wants a degraded mode wraps this scorer in ``ReliableScorer`` or
    catches this themselves.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__("Quyet returned no answer for: " + ", ".join(keys))


def _question_payload(q: Question) -> dict:
    """LabJury question -> Quyet ``questions[key]`` entry."""
    if isinstance(q, ChoiceQuestion):
        # Quyet's criteria map option -> description; LabJury options carry no
        # description, so each maps to ``null`` (the model infers from the name).
        return {
            "type": "choice",
            "instructions": q.prompt,
            "criteria": {opt: None for opt in q.options},
        }
    if isinstance(q, ScoreQuestion):
        return {"type": "score", "instructions": q.prompt, "criteria": list(q.levels)}
    if isinstance(q, NoulQuestion):
        return {"type": "noul", "instructions": q.prompt}
    raise TypeError(f"unsupported question type: {type(q).__name__}")


def _message(state: State) -> str:
    """Join the text pieces of ``state`` — the same source ``LLMJudgeScorer``
    reads. Quyet is text-only; an empty state has nothing to judge."""
    text = "\n".join(str(piece.payload) for piece in state.get("text"))
    if not text.strip():
        raise ValueError("QuyetScorer: empty text state, nothing to judge")
    return text


def _answer_for(q: Question, a: dict) -> Answer:
    """Quyet answer dict -> :class:`Answer`, per the CTO-decided mapping."""
    if isinstance(q, ChoiceQuestion):
        value = a["choice"]
        if value not in q.options:
            raise ValueError(f"Quyet choice {value!r} not in options for {q.key!r}")
        return Answer(q.key, value, a["confidence"], dict(a["probabilities"]))

    if isinstance(q, ScoreQuestion):
        # Value is the *mode* of the calibrated distribution (argmax), not the
        # continuous ``score`` — consistent with how ``choice`` is handled, and
        # optimal under 0-1 loss. ``legend`` maps the probability keys (indices)
        # to the level names; the distribution is re-keyed by level.
        legend = a["legend"]
        probs = a["probabilities"]
        top = max(probs, key=probs.__getitem__)
        value = legend[top]
        if value not in q.levels:
            raise ValueError(f"Quyet score {value!r} not in levels for {q.key!r}")
        distribution = {legend[k]: p for k, p in probs.items()}
        return Answer(q.key, value, a["confidence"], distribution)

    if isinstance(q, NoulQuestion):
        # Quyet returns ``noul`` = P(true) with NO confidence field. 0.5 is the
        # decision threshold for a calibrated binary; confidence is the mass on
        # the chosen side (DERIVED — we never pretend Quyet reported a confidence).
        noul = a["noul"]
        value = noul >= 0.5
        confidence = max(noul, 1.0 - noul)
        return Answer(q.key, value, confidence, {"true": noul, "false": 1.0 - noul})

    raise TypeError(f"unsupported question type: {type(q).__name__}")


class QuyetScorer:
    """A ``Scorer`` backed by Quyet-1.0-Large. Text-only.

    ``transport`` is injected (body dict in, parsed-JSON dict out) so the class
    imports no HTTP library and is tested with a fake. ``cost_meter``/``tenant``
    are optional: when a meter is given, each call reports its token usage into
    the shipped :class:`~labjury.cost.CostMeter` side channel.
    """

    accepts = frozenset({"text"})  # confirmed by ``input_modalities: ["text"]``

    def __init__(
        self,
        transport: Transport,
        *,
        model: str = DEFAULT_MODEL,
        cost_meter=None,
        tenant: str | None = None,
    ) -> None:
        self._transport = transport
        self._model = model
        self._cost_meter = cost_meter
        self._tenant = tenant

    async def score(self, state: State, questions: list[Question]) -> list[Answer]:
        body = {
            "model": self._model,
            "state": {"message": _message(state)},
            "questions": {q.key: _question_payload(q) for q in questions},
        }
        resp = await self._transport(body)

        usage = resp.get("usage") or {}
        if self._cost_meter is not None:
            self._cost_meter.record(
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
                tenant=self._tenant,
            )

        answers = resp.get("answers") or {}
        missing = [q.key for q in questions if q.key not in answers]
        if missing:
            raise QuyetPartialFailure(missing)

        # Aligned to the input question order.
        return [_answer_for(q, answers[q.key]) for q in questions]


def httpx_transport(api_key: str, *, base_url: str = ENDPOINT) -> Transport:
    """Turnkey transport over ``httpx`` (imported lazily — optional dependency).

    One line to a live scorer: ``QuyetScorer(httpx_transport(api_key))``. Not
    used by the tests, which inject a fake; kept out of the import path so the
    module stays zero-dependency.
    """
    async def _transport(body: dict) -> dict:
        import httpx  # lazy: imported on first request, not at factory construction

        async with httpx.AsyncClient() as client:
            r = await client.post(
                base_url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            return r.json()

    return _transport
