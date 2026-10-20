"""Immutable audit records and their serialization seam.

An :class:`AuditEvent` captures everything needed to explain and reproduce one
engine decision. It is JSON-serializable through :meth:`AuditEvent.to_dict` /
:meth:`AuditEvent.from_dict` — the single seam every storage backend touches,
so a backend never needs to understand LabJury's internal types.

Replay (:func:`replay_decision`) lives in this module too: it re-runs a
decision policy over a recorded event's inputs to reproduce the verdict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from labjury.decisions import (
    Answer,
    Candidate,
    ChoiceQuestion,
    NoulQuestion,
    Question,
    ScoreQuestion,
)
from labjury.results import Verdict
from labjury.state import State


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProvenanceRef:
    """Which plugin produced/transformed a decision, and how it was configured."""

    name: str
    version: str | None = None
    params: dict | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version, "params": self.params}

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceRef":
        return cls(d["name"], d.get("version"), d.get("params"))


@dataclass(frozen=True)
class AuditEvent:
    """One immutable record of a decision (or a cache-served reuse of one)."""

    correlation_id: str
    input_fingerprint: str
    modalities: frozenset[str] = frozenset()
    from_cache: bool = False
    used_proposer: bool | None = None
    candidates: tuple[dict, ...] = ()
    answers: tuple[dict, ...] = ()
    known_labels: frozenset[str] = frozenset()
    provenance: dict[str, ProvenanceRef] = field(default_factory=dict)
    verdict: dict | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "input_fingerprint": self.input_fingerprint,
            "modalities": sorted(self.modalities),
            "from_cache": self.from_cache,
            "used_proposer": self.used_proposer,
            "candidates": [dict(c) for c in self.candidates],
            "answers": [dict(a) for a in self.answers],
            "known_labels": sorted(self.known_labels),
            "provenance": {k: v.to_dict() for k, v in self.provenance.items()},
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEvent":
        return cls(
            correlation_id=d["correlation_id"],
            input_fingerprint=d["input_fingerprint"],
            modalities=frozenset(d.get("modalities", ())),
            from_cache=d.get("from_cache", False),
            used_proposer=d.get("used_proposer"),
            candidates=tuple(d.get("candidates", ())),
            answers=tuple(d.get("answers", ())),
            known_labels=frozenset(d.get("known_labels", ())),
            provenance={
                k: ProvenanceRef.from_dict(v) for k, v in d.get("provenance", {}).items()
            },
            verdict=d.get("verdict"),
            event_id=d["event_id"],
            occurred_at=d["occurred_at"],
        )


# -- domain-object serialization (the event stores plain dicts) --------------

def question_to_dict(q: Question) -> dict:
    if isinstance(q, ChoiceQuestion):
        return {"type": "choice", "key": q.key, "prompt": q.prompt, "options": list(q.options)}
    if isinstance(q, ScoreQuestion):
        return {"type": "score", "key": q.key, "prompt": q.prompt, "levels": list(q.levels)}
    if isinstance(q, NoulQuestion):
        return {"type": "noul", "key": q.key, "prompt": q.prompt}
    raise TypeError(f"unserializable question type: {type(q).__name__}")


def question_from_dict(d: dict) -> Question:
    kind = d["type"]
    if kind == "choice":
        return ChoiceQuestion(d["key"], d["prompt"], list(d["options"]))
    if kind == "score":
        return ScoreQuestion(d["key"], d["prompt"], list(d["levels"]))
    if kind == "noul":
        return NoulQuestion(d["key"], d["prompt"])
    raise ValueError(f"unknown question type: {kind!r}")


def candidate_to_dict(c: Candidate) -> dict:
    return {
        "label": c.label,
        "kind": c.kind,
        "question": question_to_dict(c.question),
        "rubric_version": c.rubric_version,
    }


def candidate_from_dict(d: dict) -> Candidate:
    return Candidate(
        d["label"],
        d["kind"],
        question_from_dict(d["question"]),
        rubric_version=d.get("rubric_version"),
    )


def verdict_to_dict(v: Verdict) -> dict:
    return {
        "action": v.action.value,
        "labels": v.labels,
        "scores": v.scores,
        "novel_labels": v.novel_labels,
        "reason": v.reason,
    }


def provenance_of(plugin: object) -> ProvenanceRef:
    """The provenance of a plugin instance: its class name and, if declared, its
    ``version`` and ``params`` (how it was configured)."""
    return ProvenanceRef(
        type(plugin).__name__,
        getattr(plugin, "version", None),
        getattr(plugin, "params", None),
    )


def answer_to_dict(a: Answer) -> dict:
    return {
        "key": a.key,
        "value": a.value,
        "confidence": a.confidence,
        "distribution": a.distribution,
    }


def answer_from_dict(d: dict) -> Answer:
    return Answer(d["key"], d["value"], d["confidence"], d.get("distribution"))


# -- deterministic replay ----------------------------------------------------

class _FrozenTaxonomy:
    """A read-only taxonomy pinned to a recorded snapshot.

    Only the open-world reads matter for replay; writes a policy may attempt
    (``propose``/``promote`` for novel labels) are no-ops so replay never
    mutates anything.
    """

    def __init__(self, known: frozenset[str]) -> None:
        self._known = known

    async def is_known(self, label: str) -> bool:
        return label in self._known

    async def propose(self, label: str, meta: dict | None = None) -> None:
        return None

    async def promote(self, label: str) -> None:
        return None

    async def known_labels(self) -> set[str]:
        return set(self._known)

    async def proposed_labels(self) -> set[str]:
        return set()


async def replay_decision(event: AuditEvent, policy) -> Verdict:
    """Re-run ``policy`` over a recorded event's inputs to reproduce the verdict.

    Faithful for policies that decide from candidates, answers, and the taxonomy
    snapshot (the default ``RecallBiasedPolicy``). Raises :class:`ValueError` for
    a cache-hit event — there is no decision to replay; the original decision's
    event is the replayable one.
    """
    if event.from_cache:
        raise ValueError("cannot replay a cache-hit event; replay the original decision")
    candidates = [candidate_from_dict(c) for c in event.candidates]
    answers = [answer_from_dict(a) for a in event.answers]
    taxonomy = _FrozenTaxonomy(event.known_labels)
    return await policy.decide(State(), candidates, answers, taxonomy)


def verdict_matches(event: AuditEvent, verdict: Verdict) -> bool:
    """True if ``verdict`` matches the verdict recorded on ``event``."""
    recorded = event.verdict or {}
    return (
        verdict.action.value == recorded.get("action")
        and verdict.labels == recorded.get("labels")
        and verdict.novel_labels == recorded.get("novel_labels")
        and verdict.reason == recorded.get("reason")
    )
