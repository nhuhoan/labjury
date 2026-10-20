#!/usr/bin/env bash
# Generate Python gRPC stubs from the service contract.
#
# Requires the [grpc] extra:  pip install labjury[grpc]
# The proto package is labjury.v1, so stubs land under src/labjury/v1/ and import
# as `labjury.v1.labjury_pb2` (git-ignored build artifacts). Re-run after changing
# proto/labjury/v1/labjury.proto.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/src/labjury/v1"
touch "$ROOT/src/labjury/v1/__init__.py"

python -m grpc_tools.protoc \
  -I "$ROOT/proto" \
  --python_out="$ROOT/src" \
  --grpc_python_out="$ROOT/src" \
  "$ROOT/proto/labjury/v1/labjury.proto"

echo "generated src/labjury/v1/labjury_pb2.py and labjury_pb2_grpc.py"
