"""Versioned, storage-agnostic registry of ``label → Question`` rubrics.

A *rubric* is the question (the criteria) asked about a label — for ``violence``,
the :class:`~labjury.decisions.Question` "Does this contain graphic violence?".
:class:`Rubric` pairs that question with a version string so a decision can
record which revision it used (the audit/reproducibility link lives on
:class:`~labjury.decisions.Candidate.rubric_version`).

LabJury owns the registry *mechanism*, not the rubric *content*: what the
questions say and how versions are named is the deployer's domain. A published
``(label, version)`` is immutable — that is what makes it a reproducibility
handle. :class:`InMemoryRubricStore` is the zero-dependency reference backend;
durable backends are bring-your-own (see :func:`labjury.testing.assert_rubric_store_contract`).
"""

from __future__ import annotations

from dataclasses import dataclass

from labjury.decisions import Question


@dataclass(frozen=True)
class Rubric:
    """A versioned rubric for one label."""

    label: str
    question: Question
    version: str


class InMemoryRubricStore:
    """Reference :class:`~labjury.plugins.RubricStore`; the current rubric for a
    label is its most recently registered version. History is retained."""

    def __init__(self) -> None:
        self._by_label: dict[str, dict[str, Rubric]] = {}

    async def register(self, label: str, question: Question, version: str) -> Rubric:
        versions = self._by_label.setdefault(label, {})
        existing = versions.get(version)
        if existing is not None:
            if existing.question != question:
                raise ValueError(
                    f"rubric {label!r} version {version!r} already published with a "
                    "different question; a published version is immutable"
                )
            return existing
        rubric = Rubric(label, question, version)
        versions[version] = rubric
        return rubric

    async def resolve(self, label: str) -> Rubric | None:
        versions = self._by_label.get(label)
        if not versions:
            return None
        return next(reversed(versions.values()))

    async def get(self, label: str, version: str) -> Rubric | None:
        return self._by_label.get(label, {}).get(version)

    async def history(self, label: str) -> list[str]:
        return list(self._by_label.get(label, {}))
