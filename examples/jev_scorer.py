"""JevScorer — a reference multimodal ``Scorer`` for Jev / System One (example).

Jev (TypeSafe AI's "System One", ``POST https://api.typesafe.ai/v1/systemone``)
is a calibrated decision model: it reads a state and typed questions and returns
calibrated options — verbatim the LabJury :class:`~labjury.plugins.Scorer`
contract. Quyet is its text-only sibling; **Jev also takes images**, so this is
the worked *multimodal* adapter the framework's multimodal support
(``docs/multimodal.md``) exists to serve.

Like the Quyet example, this lives in ``examples/`` on purpose and injects its
``transport`` (HTTP + auth), so the class imports no third party and tests run
offline against a fake. The optional :func:`httpx_transport` factory is the
turnkey path; it sets Jev's image opt-in header when the request carries assets.

**How an image goes on the wire is Jev's contract, not LabJury's** — that is the
line ``docs/multimodal.md`` draws. Here: each ``Content("image", …)`` becomes a
base64-inline *asset*; the model sees the state text plus every asset, and the
questions are asked against the whole thing.

Mapping to LabJury questions:
  - ``ChoiceQuestion`` -> Jev ``choice``  (options -> criteria, no descriptions)
  - ``ScoreQuestion``  -> Jev ``score``   (levels -> ordered criteria)
  - ``NoulQuestion``   -> Jev ``noul``
Jev's ``box`` type (image localization -> a bounding box) has **no LabJury
question primitive**, so it is deliberately out of scope here; see non-goals in
``docs/superpowers/specs/2026-10-22-jev-scorer-design.md``.
"""

from __future__ import annotations

import base64
from typing import Awaitable, Callable

from labjury import (
    Answer,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
    State,
)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
IMAGE_HEADER = "TypeSafe-Danger-Zone-Images"  # Jev requires this when sending images

Transport = Callable[[dict], Awaitable[dict]]


class JevMissingAnswer(Exception):
    """Jev returned no answer for one or more questions (fail-closed).

    Jev validates requests up front (HTTP 422), so a 2xx that omits a question is
    unexpected — but a *missing* judgment in a gating/labeling system must
    surface, never be fabricated as a low-confidence answer that flows into
    block/hold. Wrap in ``ReliableScorer`` or catch this for a degraded mode.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__("Jev returned no answer for: " + ", ".join(keys))


def _question_payload(q: Question) -> dict:
    """LabJury question -> Jev ``questions[key]`` entry."""
    if isinstance(q, ChoiceQuestion):
        # Jev criteria map option -> description; LabJury options carry none, so
        # each maps to ``null`` (the model reads the option name).
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


def _image_asset(payload, meta: dict | None) -> dict:
    """``Content("image", …)`` -> a Jev base64-inline image asset.

    ``payload`` may be raw ``bytes`` (we base64-encode it) or an already-encoded
    base64 ``str``. ``format`` comes from ``meta['format']``, else the subtype of
    ``meta['mime']`` (``image/png`` -> ``png``), defaulting to ``png``.
    """
    meta = meta or {}
    if isinstance(payload, bytes):
        data_base64 = base64.b64encode(payload).decode("ascii")
    elif isinstance(payload, str):
        data_base64 = payload  # assumed already base64
    else:
        raise TypeError(
            f"image payload must be bytes or base64 str, got {type(payload).__name__}"
        )
    fmt = meta.get("format")
    if fmt is None:
        mime = meta.get("mime", "image/png")
        fmt = mime.split("/")[-1]
    return {"type": "image", "format": fmt, "data_base64": data_base64}


def _answer_for(q: Question, a: dict) -> Answer:
    """Jev answer dict -> :class:`Answer` (identical calibrated mapping to Quyet)."""
    if isinstance(q, ChoiceQuestion):
        value = a["choice"]
        if value not in q.options:
            raise ValueError(f"Jev choice {value!r} not in options for {q.key!r}")
        return Answer(q.key, value, a["confidence"], dict(a["probabilities"]))

    if isinstance(q, ScoreQuestion):
        # Value = mode (argmax of the calibrated distribution), not the continuous
        # probability-weighted ``score`` — consistent with ``choice``. ``legend``
        # maps probability keys (indices) to level names; re-key the distribution.
        legend = a["legend"]
        probs = a["probabilities"]
        value = legend[max(probs, key=probs.__getitem__)]
        if value not in q.levels:
            raise ValueError(f"Jev score {value!r} not in levels for {q.key!r}")
        return Answer(q.key, value, a["confidence"], {legend[k]: p for k, p in probs.items()})

    if isinstance(q, NoulQuestion):
        # Jev returns ``noul`` = P(true) with NO confidence field. 0.5 is the
        # threshold; confidence is the mass on the chosen side (DERIVED — we never
        # pretend Jev reported a confidence).
        noul = a["noul"]
        return Answer(q.key, noul >= 0.5, max(noul, 1.0 - noul),
                      {"true": noul, "false": 1.0 - noul})

    raise TypeError(f"unsupported question type: {type(q).__name__}")


class JevScorer:
    """A multimodal ``Scorer`` backed by Jev / System One. Accepts text + image.

    ``transport`` is injected (body dict in, parsed-JSON dict out). When the state
    carries images, this scorer adds an ``assets`` map to the body; the transport
    is responsible for setting the ``TypeSafe-Danger-Zone-Images`` header (the
    bundled :func:`httpx_transport` does so automatically when assets are present).
    """

    accepts = frozenset({"text", "image"})

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
        text = "\n".join(str(piece.payload) for piece in state.get("text"))
        images = state.get("image")
        if not text.strip() and not images:
            raise ValueError("JevScorer: empty state, nothing to judge")

        body: dict = {
            "model": self._model,
            "state": text,
            "questions": {q.key: _question_payload(q) for q in questions},
        }
        if images:
            body["assets"] = {
                f"image_{i}": _image_asset(piece.payload, piece.meta)
                for i, piece in enumerate(images)
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
            raise JevMissingAnswer(missing)

        return [_answer_for(q, answers[q.key]) for q in questions]


def httpx_transport(api_key: str, *, base_url: str = ENDPOINT) -> Transport:
    """Turnkey transport over ``httpx`` (imported lazily — optional dependency).

    Sets Jev's image opt-in header automatically when the request body carries
    ``assets``, so the scorer stays wire-agnostic. Not exercised by the tests,
    which inject a fake.
    """
    async def _transport(body: dict) -> dict:
        import httpx  # lazy: imported on first request, not at factory construction

        headers = {"Authorization": f"Bearer {api_key}"}
        if body.get("assets"):
            headers[IMAGE_HEADER] = "true"
        async with httpx.AsyncClient() as client:
            r = await client.post(base_url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

    return _transport
