"""Stateless engine orchestration for the gRPC service.

Pure Python — no grpc import. The generated servicer (in ``server.py``) unpacks
proto messages into these plain arguments, calls the handler, and packs the wire
dicts back into proto responses. Keeping the orchestration here makes it fully
unit-testable without a running server.
"""

from __future__ import annotations

from labjury.service.translation import item_from_wire, result_to_wire


class DecisionHandler:
    """Runs items through the engine and returns wire-shaped responses."""

    def __init__(self, engine) -> None:
        self._engine = engine

    async def decide(self, correlation_id: str, raw: dict, tenant: str | None) -> dict:
        item = item_from_wire(correlation_id, raw, tenant)
        result = await self._engine.process(item)
        return result_to_wire(result)

    async def decide_batch(
        self, items: list[tuple[str, dict, str | None]]
    ) -> list[dict]:
        labj_items = [item_from_wire(cid, raw, tenant) for cid, raw, tenant in items]
        results = await self._engine.process_batch(labj_items)
        return [result_to_wire(r) for r in results]
