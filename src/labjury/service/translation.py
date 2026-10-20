"""Pure domain <-> wire translation for the gRPC service.

Proto-agnostic by design: it works on plain Python values and emits the proto
enum *names* as strings, so the semantically important status/action mapping is
unit-testable without compiled proto enums. The server does the trivial
name<->int conversion at the edge. No grpc/protobuf import here.
"""

from __future__ import annotations

from labjury.results import Action, ItemResult, Status, Verdict
from labjury.state import Item

_STATUS_TO_WIRE: dict[Status, str] = {
    Status.DECIDED: "STATUS_DECIDED",
    Status.REVIEW: "STATUS_REVIEW",
    Status.FAILED: "STATUS_FAILED",
    Status.RETRY_LATER: "STATUS_RETRY_LATER",
}

_ACTION_TO_WIRE: dict[Action, str] = {
    Action.ACCEPT: "ACTION_ACCEPT",
    Action.BLOCK: "ACTION_BLOCK",
    Action.REVIEW: "ACTION_REVIEW",
}


def item_from_wire(correlation_id: str, raw: dict, tenant: str | None) -> Item:
    """Build an engine :class:`~labjury.state.Item` from wire fields.

    An empty-string tenant (the proto default for an unset field) becomes ``None``.
    """
    return Item(correlation_id, raw, tenant=tenant or None)


def _verdict_to_wire(verdict: Verdict) -> dict:
    return {
        "action": _ACTION_TO_WIRE[verdict.action],
        "labels": list(verdict.labels),
        "scores": dict(verdict.scores),
        "novel_labels": list(verdict.novel_labels),
        "reason": verdict.reason,
    }


def result_to_wire(result: ItemResult) -> dict:
    """Map an :class:`~labjury.results.ItemResult` to the wire response shape.

    ``verdict`` is ``None`` when the result carries none (e.g. a FAILED item);
    ``error``/``latency_ms``/``tenant`` use the proto defaults (``""``/``0.0``/``""``)
    when absent.
    """
    return {
        "correlation_id": result.correlation_id,
        "status": _STATUS_TO_WIRE[result.status],
        "verdict": _verdict_to_wire(result.verdict) if result.verdict else None,
        "error": result.error or "",
        "latency_ms": result.latency_ms or 0.0,
        "tenant": result.tenant or "",
    }
