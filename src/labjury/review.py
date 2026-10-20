"""Human-in-the-loop review — a stateless, fire-and-forget hand-off contract.

The engine decides ``Status.REVIEW`` when a policy wants a human to adjudicate.
LabJury owns the *contract* for that hand-off, not the queue: it packages a
:class:`ReviewTask`, the deployer hands it to their own review backend (a
ticketing system, a labeling tool, a broker) via a :class:`~labjury.plugins.ReviewQueue`,
and when a human decides, a :class:`ReviewResolution` converts back to a final
:class:`~labjury.results.Verdict`. The framework never runs a consumer loop or
holds state waiting — orchestration stays with the deployer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from labjury.audit import AuditEvent
from labjury.results import Action, Verdict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ReviewTask:
    """What a human needs to adjudicate one flagged decision. Portable: it crosses
    to an external review system, so it is JSON-serializable."""

    correlation_id: str
    candidates: tuple[dict, ...] = ()
    answers: tuple[dict, ...] = ()
    tentative_verdict: dict | None = None
    tenant: str | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "candidates": [dict(c) for c in self.candidates],
            "answers": [dict(a) for a in self.answers],
            "tentative_verdict": self.tentative_verdict,
            "tenant": self.tenant,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReviewTask":
        return cls(
            correlation_id=d["correlation_id"],
            candidates=tuple(d.get("candidates", ())),
            answers=tuple(d.get("answers", ())),
            tentative_verdict=d.get("tentative_verdict"),
            tenant=d.get("tenant"),
            created_at=d.get("created_at", _now_iso()),
        )


@dataclass(frozen=True)
class ReviewResolution:
    """A human's decision on a :class:`ReviewTask`. Portable (comes back from an
    external system)."""

    correlation_id: str
    action: str
    labels: list[str]
    reviewer: str
    note: str = ""
    decided_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "action": self.action,
            "labels": list(self.labels),
            "reviewer": self.reviewer,
            "note": self.note,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReviewResolution":
        return cls(
            correlation_id=d["correlation_id"],
            action=d["action"],
            labels=list(d.get("labels", [])),
            reviewer=d["reviewer"],
            note=d.get("note", ""),
            decided_at=d.get("decided_at", _now_iso()),
        )

    def to_verdict(self) -> Verdict:
        """The human decision as a final verdict. Scores are empty — a human
        produced no model scores. Raises ``ValueError`` on an unknown action."""
        return Verdict(
            Action(self.action),
            list(self.labels),
            {},
            [],
            self.note or f"human review by {self.reviewer}",
        )


class InMemoryReviewQueue:
    """Reference :class:`~labjury.plugins.ReviewQueue`; holds enqueued tasks in a
    list. ``pending`` inspects, ``drain`` pulls-and-clears (both return copies)."""

    def __init__(self) -> None:
        self._tasks: list[ReviewTask] = []

    async def enqueue(self, task: ReviewTask) -> None:
        self._tasks.append(task)

    def pending(self) -> list[ReviewTask]:
        return list(self._tasks)

    def drain(self) -> list[ReviewTask]:
        tasks = list(self._tasks)
        self._tasks.clear()
        return tasks


def review_task_from_event(event: AuditEvent) -> ReviewTask:
    """Build a :class:`ReviewTask` from a recorded decision — the audit event
    already carries the candidates, answers, tentative verdict, and tenant."""
    return ReviewTask(
        correlation_id=event.correlation_id,
        candidates=tuple(event.candidates),
        answers=tuple(event.answers),
        tentative_verdict=event.verdict,
        tenant=event.tenant,
    )
