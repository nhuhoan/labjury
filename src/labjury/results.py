"""Verdict and per-item result types.

:class:`Status` values map onto the ``process_batch`` public-API contract:
every item yields exactly one :class:`ItemResult` carrying its correlation id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Action(Enum):
    ACCEPT = "accept"
    BLOCK = "block"
    REVIEW = "review"


class Status(Enum):
    DECIDED = "decided"
    REVIEW = "review"
    FAILED = "failed"
    RETRY_LATER = "retry_later"


@dataclass
class Verdict:
    action: Action
    labels: list[str]
    scores: dict[str, float]
    novel_labels: list[str]
    reason: str


@dataclass
class ItemResult:
    correlation_id: str
    status: Status
    verdict: Verdict | None = None
    error: str | None = None
