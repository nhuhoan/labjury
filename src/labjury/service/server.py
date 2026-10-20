"""Reference gRPC server binding — the thin transport glue over DecisionHandler.

Importing this module needs no grpc: the grpc runtime and the protoc-generated
stubs are imported **lazily inside** :func:`serve`, and the servicer class (which
must subclass a generated base) is built there too. So the module is importable
(and the handler it delegates to is unit-tested) even when ``labjury[grpc]`` is
not installed and the stubs have not been generated.

This binding is deliberately minimal reference code: transport concerns (TLS,
authn/z, interceptors, a REST gateway, rate limiting) belong to the deployer's
deployment layer, not here.
"""

from __future__ import annotations

from labjury.service.handler import DecisionHandler

_MISSING = (
    "The gRPC server needs the optional transport and generated stubs. Install "
    "them with `pip install labjury[grpc]` and generate the stubs with "
    "`bash scripts/gen_proto.sh`."
)


async def serve(engine, address: str = "[::]:50051"):
    """Start a stateless gRPC server delegating to the engine; serve until terminated.

    Raises :class:`RuntimeError` (with the setup command) if grpc or the generated
    stubs are unavailable.
    """
    try:
        import grpc
        from google.protobuf.json_format import MessageToDict

        from labjury.v1 import labjury_pb2, labjury_pb2_grpc
    except ImportError as exc:  # pragma: no cover - needs the [grpc] extra + stubs
        raise RuntimeError(_MISSING) from exc

    handler = DecisionHandler(engine)

    def _verdict_msg(wire: dict | None):
        if wire is None:
            return None
        return labjury_pb2.Verdict(
            action=labjury_pb2.Action.Value(wire["action"]),
            labels=wire["labels"],
            scores=wire["scores"],
            novel_labels=wire["novel_labels"],
            reason=wire["reason"],
        )

    def _response_msg(wire: dict):
        return labjury_pb2.DecideResponse(
            correlation_id=wire["correlation_id"],
            status=labjury_pb2.Status.Value(wire["status"]),
            verdict=_verdict_msg(wire["verdict"]),
            error=wire["error"],
            latency_ms=wire["latency_ms"],
            tenant=wire["tenant"],
        )

    def _item_fields(item) -> tuple[str, dict, str]:
        raw = MessageToDict(item.raw) if item.HasField("raw") else {}
        return item.id, raw, item.tenant

    class _Servicer(labjury_pb2_grpc.LabJuryServiceServicer):  # pragma: no cover
        async def Decide(self, request, context):
            cid, raw, tenant = _item_fields(request.item)
            wire = await handler.decide(cid, raw, tenant)
            return _response_msg(wire)

        async def DecideBatch(self, request, context):
            items = [_item_fields(i) for i in request.items]
            wires = await handler.decide_batch(items)
            return labjury_pb2.DecideBatchResponse(
                results=[_response_msg(w) for w in wires]
            )

    server = grpc.aio.server()
    labjury_pb2_grpc.add_LabJuryServiceServicer_to_server(_Servicer(), server)
    server.add_insecure_port(address)
    await server.start()
    await server.wait_for_termination()
