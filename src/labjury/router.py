"""Capability-aware, per-item router.

The capability graph (which scorer can consume which modalities) is fixed by
the plugins' ``accepts`` sets, but the *path an individual item takes* is
decided at runtime from its content. The visual-fast-path lets a purely
visual item skip the expensive Proposer and go straight to an image-capable
scorer.
"""

from __future__ import annotations

from dataclasses import dataclass

from labjury.plugins import Proposer, Scorer
from labjury.state import State


#: Modalities a scorer can judge directly from the pixels, so a purely visual
#: item may skip the (expensive, generative) Proposer. Defined positively:
#: anything *not* in this set (text, metadata, audio, …) needs the semantic
#: long route. Extend this set to open the fast path to a new visual modality.
VISUAL_MODALITIES = frozenset({"image", "frame_sequence"})


class NoRouteError(Exception):
    """No registered scorer can consume this item's modalities."""


@dataclass
class Route:
    use_proposer: bool
    scorer: Scorer


class Router:
    def __init__(self, proposers: list[Proposer], scorers: list[Scorer]) -> None:
        self._proposers = proposers
        self._scorers = scorers

    def route(self, state: State) -> Route:
        modalities = state.modalities()
        scorer = self._first_matching_scorer(modalities)
        if scorer is None:
            raise NoRouteError(f"no scorer accepts modalities {sorted(modalities)}")
        purely_visual = bool(modalities) and modalities <= VISUAL_MODALITIES
        needs_semantic = not purely_visual or "needs_semantic" in state.flags
        return Route(use_proposer=needs_semantic, scorer=scorer)

    def _first_matching_scorer(self, modalities: set[str]) -> Scorer | None:
        for scorer in self._scorers:
            if "*" in scorer.accepts or modalities <= set(scorer.accepts):
                return scorer
        return None
