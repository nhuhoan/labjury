"""Plugin registry — programmatic registration plus entry-point discovery.

Third parties ship ``pip`` packages that register plugins via entry-point
groups ``labjury.<kind>`` without any change to the core.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Callable

_KINDS = (
    "context_builders",
    "proposers",
    "scorers",
    "policies",
    "sinks",
    "taxonomies",
    "caches",
    "audit_logs",
)

_REGISTRY: dict[str, dict[str, Callable[[], Any]]] = {}


def register(kind: str, name: str, factory: Callable[[], Any]) -> None:
    _REGISTRY.setdefault(kind, {})[name] = factory


def get(kind: str, name: str) -> Any:
    try:
        factory = _REGISTRY[kind][name]
    except KeyError as exc:
        raise KeyError(f"no plugin {name!r} registered under {kind!r}") from exc
    return factory()


def available(kind: str) -> list[str]:
    return sorted(_REGISTRY.get(kind, {}).keys())


def clear() -> None:
    _REGISTRY.clear()


def load_entry_points(prefix: str = "labjury") -> None:
    eps = entry_points()
    for kind in _KINDS:
        for ep in eps.select(group=f"{prefix}.{kind}"):
            register(kind, ep.name, ep.load())
