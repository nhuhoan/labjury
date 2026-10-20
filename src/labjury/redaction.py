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
