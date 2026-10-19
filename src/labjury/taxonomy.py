"""Default, in-memory open-world taxonomy.

A label's life: ``propose`` (seen, pending human review) → ``promote``
(official). ``is_known`` is true only once promoted, so content matching no
*official* label is never silently absorbed — it surfaces as a proposal.
"""

from __future__ import annotations


class InMemoryTaxonomyStore:
    def __init__(self) -> None:
        self._official: set[str] = set()
        self._proposed: set[str] = set()

    async def is_known(self, label: str) -> bool:
        return label in self._official

    async def propose(self, label: str, meta: dict | None = None) -> None:
        if label not in self._official:
            self._proposed.add(label)

    async def promote(self, label: str) -> None:
        self._proposed.discard(label)
        self._official.add(label)

    async def known_labels(self) -> set[str]:
        return set(self._official)

    async def proposed_labels(self) -> set[str]:
        return set(self._proposed)
