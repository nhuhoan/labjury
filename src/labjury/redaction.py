"""The PII-redaction standard — model-agnostic, zero-dependency.

Content classified by LabJury routinely carries personal data. The highest-risk
moment is when it crosses the deployer's trust boundary into a prompt sent to a
remote model. These wrappers put a redaction **seam** exactly there: they mask
the ``State`` copy a remote ``Scorer`` / ``Proposer`` is about to see and leave
the engine's held ``State`` — the one the policy and sink see — untouched.

Nothing here is a PII *detector*: "what counts as PII" is a policy/law question
every company answers differently, so they plug their own :class:`Redactor`
(Presidio, cloud DLP, an in-house NER model) behind the protocol. :class:`RegexRedactor`
is a zero-dependency baseline, **not** a compliance control.

Fail-closed by construction: a redactor that raises propagates (the engine's
partial-failure path turns it into ``ItemResult(FAILED)``); with ``strict=True``
(the default) a modality the redactor does not cover raises
:class:`UnredactedModalityError` *before* anything reaches the model.
"""

from __future__ import annotations

import re

from labjury.state import Content, State


class UnredactedModalityError(Exception):
    """Raised (strict mode) when the state carries a modality the redactor does
    not cover, so the content is not sent to the model unredacted."""


def _guard(redactor, state: State, strict: bool) -> None:
    if not strict or "*" in redactor.accepts:
        return
    uncovered = state.modalities() - redactor.accepts
    if uncovered:
        raise UnredactedModalityError(
            f"redactor does not cover modalities: {sorted(uncovered)}"
        )


class RedactingScorer:
    """Redacts the ``State`` handed to an inner remote ``Scorer``."""

    def __init__(self, inner, redactor, *, strict: bool = True) -> None:
        self._inner = inner
        self._redactor = redactor
        self._strict = strict
        self.accepts = inner.accepts

    async def score(self, state, questions):
        _guard(self._redactor, state, self._strict)
        redacted = await self._redactor.redact(state)
        return await self._inner.score(redacted, questions)


class RedactingProposer:
    """Redacts the ``State`` handed to an inner remote ``Proposer``."""

    def __init__(self, inner, redactor, *, strict: bool = True) -> None:
        self._inner = inner
        self._redactor = redactor
        self._strict = strict
        self.accepts = inner.accepts

    async def propose(self, state, context):
        _guard(self._redactor, state, self._strict)
        redacted = await self._redactor.redact(state)
        return await self._inner.propose(redacted, context)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b\d{4}(?:[ -]?\d{4}){3}\b")
_PHONE = re.compile(r"\+?\d(?:[ -]?\d){8,}")


class RegexRedactor:
    """Zero-dependency baseline redactor for obvious text patterns.

    Masks emails, phone-shaped digit runs, and card-shaped digit groups in
    every ``text`` content. **Baseline only, not a compliance control**: it
    misses names, addresses, non-text PII, and obfuscated forms. Companies with
    real obligations plug a proper :class:`~labjury.plugins.Redactor` (Presidio,
    cloud DLP, an in-house NER model) behind the same protocol.
    """

    accepts = frozenset({"text"})

    async def redact(self, state: State) -> State:
        out = State()
        out.flags = set(state.flags)
        for mod in state.modalities():
            for c in state.get(mod):
                if c.modality == "text":
                    out.add(Content("text", self._mask(c.payload), c.meta))
                else:
                    out.add(c)
        return out

    @staticmethod
    def _mask(text: str) -> str:
        # card before phone: a card is a superset of the phone shape
        text = _EMAIL.sub("[EMAIL]", text)
        text = _CARD.sub("[CARD]", text)
        text = _PHONE.sub("[PHONE]", text)
        return text
