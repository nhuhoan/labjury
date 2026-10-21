"""Immutable audit records and their serialization seam.

An :class:`AuditEvent` captures everything needed to explain and reproduce one
engine decision. It is JSON-serializable through :meth:`AuditEvent.to_dict` /
:meth:`AuditEvent.from_dict` — the single seam every storage backend touches,
so a backend never needs to understand LabJury's internal types.

Replay (:func:`replay_decision`) lives in this module too: it re-runs a
decision policy over a recorded event's inputs to reproduce the verdict.
"""

from __future__ import annotations

import hashlib
import json
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
from labjury.results import Action, Verdict
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
    tenant: str | None = None
    state_fingerprint: str | None = None
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
            "tenant": self.tenant,
            "state_fingerprint": self.state_fingerprint,
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
            tenant=d.get("tenant"),
            state_fingerprint=d.get("state_fingerprint"),
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


def verdict_from_dict(d: dict) -> Verdict:
    """Inverse of :func:`verdict_to_dict` — rebuild a :class:`Verdict` from its
    JSON-safe mapping (backends deserialize cached verdicts through this seam)."""
    return Verdict(
        Action(d["action"]),
        list(d["labels"]),
        dict(d["scores"]),
        list(d["novel_labels"]),
        d["reason"],
    )


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


def state_fingerprint(state: State) -> str:
    """Hash policy-visible state without placing its contents in the audit log."""
    content = [
        {"modality": modality, "payload": piece.payload, "meta": piece.meta}
        for modality in sorted(state.modalities())
        for piece in state.get(modality)
    ]
    blob = json.dumps(
        {"content": content, "flags": sorted(state.flags)},
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(blob).hexdigest()


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


async def replay_decision(event: AuditEvent, policy, *, state: State) -> Verdict:
    """Re-run ``policy`` over a recorded event's inputs to reproduce the verdict.

    The caller supplies the original State because audit records do not store raw
    content. For new records its fingerprint is checked before calling the policy.
    Cache-hit events have no decision to replay.
    """
    if event.from_cache:
        raise ValueError("cannot replay a cache-hit event; replay the original decision")
    if not isinstance(state, State):
        raise TypeError("replay requires the original State")
    if (
        event.state_fingerprint is not None
        and state_fingerprint(state) != event.state_fingerprint
    ):
        raise ValueError("state does not match the audited decision")
    candidates = [candidate_from_dict(c) for c in event.candidates]
    answers = [answer_from_dict(a) for a in event.answers]
    taxonomy = _FrozenTaxonomy(event.known_labels)
    return await policy.decide(state, candidates, answers, taxonomy)


def verdict_matches(event: AuditEvent, verdict: Verdict) -> bool:
    """True if ``verdict`` matches the verdict recorded on ``event``."""
    recorded = event.verdict or {}
    return (
        verdict.action.value == recorded.get("action")
        and verdict.labels == recorded.get("labels")
        and verdict.scores == recorded.get("scores")
        and verdict.novel_labels == recorded.get("novel_labels")
        and verdict.reason == recorded.get("reason")
    )


# -- reproducibility verification --------------------------------------------

@dataclass(frozen=True)
class VersionChange:
    """One component's recorded version against its current one, as
    ``"Name@version"`` on each side."""

    recorded: str | None
    current: str | None


@dataclass(frozen=True)
class ReplayReport:
    """The outcome of verifying a recorded decision against a live policy."""

    verdict_matches: bool
    drift: dict[str, VersionChange]
    recorded_verdict: dict | None
    replayed_verdict: dict

    @property
    def faithful(self) -> bool:
        """A trustworthy reproduction: same verdict **and** no version drift."""
        return self.verdict_matches and not self.drift


async def verify_replay(event: AuditEvent, policy, *, state: State) -> ReplayReport:
    """Replay ``event`` through ``policy`` and verify the reproduction.

    Re-runs the policy over the event's recorded inputs (raising
    :class:`ValueError` for a cache-hit event, like :func:`replay_decision`),
    checks the replayed verdict against the recorded one, and detects version
    drift between the policy recorded on the event and the one passed in. Only
    the policy stage is replayed — the scorer's output is pinned by the recorded
    answers. Drift compares ``(name, version)``; ``params`` is configuration, not
    a version handle, so it is not part of the drift signal.
    """
    replayed = await replay_decision(event, policy, state=state)
    matches = verdict_matches(event, replayed)
    drift: dict[str, VersionChange] = {}
    recorded = event.provenance.get("policy")
    current = provenance_of(policy)
    if recorded is not None and (
        recorded.name != current.name or recorded.version != current.version
    ):
        drift["policy"] = VersionChange(
            f"{recorded.name}@{recorded.version}",
            f"{current.name}@{current.version}",
        )
    return ReplayReport(matches, drift, event.verdict, verdict_to_dict(replayed))


@dataclass(frozen=True)
class RubricDrift:
    """One recorded candidate whose rubric no longer matches the registry.

    ``registry_question`` is ``None`` when the version is absent from the
    registry; otherwise it is the registry's serialized question, against which
    ``recorded_question`` differed.
    """

    label: str
    version: str
    reason: str
    recorded_question: dict
    registry_question: dict | None


async def rubric_drift(event: AuditEvent, store) -> list[RubricDrift]:
    """Compare each recorded candidate's rubric against what ``store`` holds.

    For every candidate carrying a ``rubric_version``, fetch
    ``await store.get(label, version)`` and compare the recorded question to the
    registry's. A published ``(label, version)`` is immutable by contract, so any
    mismatch is a real signal: the version is **absent from the registry**, or
    its **question differs**. Candidates without a ``rubric_version`` are skipped
    (they were not sourced from a registry), and a cache-hit / no-candidate event
    yields ``[]``. Detection only — what to do about drift is the deployer's.
    """
    drifts: list[RubricDrift] = []
    for cand in event.candidates:
        version = cand.get("rubric_version")
        if version is None:
            continue
        stored = await store.get(cand["label"], version)
        if stored is None:
            drifts.append(
                RubricDrift(
                    cand["label"],
                    version,
                    "version absent from registry",
                    cand["question"],
                    None,
                )
            )
            continue
        registry_question = question_to_dict(stored.question)
        if registry_question != cand["question"]:
            drifts.append(
                RubricDrift(
                    cand["label"],
                    version,
                    "question differs from registry",
                    cand["question"],
                    registry_question,
                )
            )
    return drifts
