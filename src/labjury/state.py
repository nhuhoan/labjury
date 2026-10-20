"""Multimodal, extensible state.

Modalities are an open registry of strings, never a closed enum. Adding a
new input type is a call to :func:`register_content_type`, not a core edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_BUILTIN_MODALITIES = (
    "text",
    "json",
    "image",
    "audio",
    "metadata",
    "frame_sequence",
)

_CONTENT_TYPES: set[str] = set(_BUILTIN_MODALITIES)


def register_content_type(name: str) -> None:
    """Register a new modality. Idempotent."""
    _CONTENT_TYPES.add(name)


def is_content_type(name: str) -> bool:
    """True if ``name`` is a registered modality."""
    return name in _CONTENT_TYPES


@dataclass
class Content:
    """One typed piece of an item's state."""

    modality: str
    payload: Any
    meta: dict | None = None

    def __post_init__(self) -> None:
        if not is_content_type(self.modality):
            raise ValueError(f"unregistered modality: {self.modality!r}")


class State:
    """An open container of :class:`Content`, plus mutable routing ``flags``."""

    def __init__(self) -> None:
        self._contents: list[Content] = []
        self.flags: set[str] = set()

    def add(self, content: Content) -> None:
        self._contents.append(content)

    def get(self, modality: str) -> list[Content]:
        return [c for c in self._contents if c.modality == modality]

    def has(self, modality: str) -> bool:
        return any(c.modality == modality for c in self._contents)

    def modalities(self) -> set[str]:
        return {c.modality for c in self._contents}


@dataclass
class Item:
    """An input unit. ``id`` is the correlation id carried through to the result."""

    id: str
    raw: Any
    meta: dict | None = None
    tenant: str | None = None
