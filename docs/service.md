# gRPC service & polyglot clients

Application teams in Java, Go, PHP (and Python) consume LabJury through a **stateless
gRPC service** that wraps the engine. The service is a thin adapter: each RPC runs an
item (or a batch) through `engine.process` / `process_batch` and returns the verdict.
In-process plugin extension stays Python-only — the gRPC boundary is how other
languages integrate, without cross-language FFI.

The contract is one file: [`proto/labjury/v1/labjury.proto`](../proto/labjury/v1/labjury.proto).
Every client, in every language, is generated from it.

## The contract

```proto
service LabJuryService {
  rpc Decide(DecideRequest) returns (DecideResponse);
  rpc DecideBatch(DecideBatchRequest) returns (DecideBatchResponse);
}
```

- `Item { id, google.protobuf.Struct raw, tenant }` — `raw` carries arbitrary
  JSON-like input (e.g. `{"text": "..."}`) to any language; `tenant` is optional.
- `DecideResponse { correlation_id, Status status, Verdict verdict, error, latency_ms,
  tenant }` — `verdict` is unset for a non-decided result (e.g. `STATUS_FAILED`, with
  `error` set).
- `Status` / `Action` enum values are globally prefixed (`STATUS_*`, `ACTION_*`).

The proto package `labjury.v1` versions the wire contract on its own axis, independent
of the Python package's `labjury.__version__`. A breaking wire change means a new
`vN` package.

## Running the Python server

```bash
pip install "labjury[grpc]"
bash scripts/gen_proto.sh          # generates src/labjury/v1/ stubs (git-ignored)
```

```python
import asyncio, labjury as lj
from labjury.service.server import serve

engine = lj.Engine(...)            # your configured engine
asyncio.run(serve(engine, "[::]:50051"))
```

The server is stateless reference glue: the tested logic lives in the pure
`labjury.service.translation` (domain ↔ wire) and `labjury.service.handler`
(`DecisionHandler`, the engine orchestration). Importing `labjury` never pulls in
grpc — the server imports it lazily.

## Generating clients

All clients come from the same `.proto`:

```bash
# Python
python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/labjury/v1/labjury.proto

# Go
protoc -I proto --go_out=. --go-grpc_out=. proto/labjury/v1/labjury.proto

# Java (gRPC plugin)
protoc -I proto --java_out=java/src --grpc-java_out=java/src proto/labjury/v1/labjury.proto

# PHP
protoc -I proto --php_out=php/ --grpc_out=php/ --plugin=protoc-gen-grpc=$(which grpc_php_plugin) proto/labjury/v1/labjury.proto
```

A client calls `Decide`/`DecideBatch` and reads the `Status`/`Verdict` — no Python on
the consumer side.

## What the deployer owns

The service is intentionally minimal. Transport and operational concerns are the
deployment layer's, not the framework's:

- **TLS, authentication, authorization, interceptors** — add them to your server
  (`grpc` secure credentials / an interceptor) or a sidecar.
- **A REST/JSON gateway** — front the service with grpc-gateway/Envoy if you need HTTP.
- **Rate limiting, quotas, load balancing** — your infrastructure.
- **State** — there is none in the service; the engine and its plugins hold what state
  there is (taxonomy, cache, audit, rubrics), via the backends you plug in.
