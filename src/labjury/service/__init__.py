"""Optional gRPC reference service wrapping the engine.

This subpackage is **never** imported by ``import labjury`` — the core stays
zero-dependency. ``translation`` and ``handler`` are pure stdlib and testable
without grpc; only ``server`` imports grpc (lazily). Install the transport with
``pip install labjury[grpc]`` and generate stubs with ``scripts/gen_proto.sh``.
"""
