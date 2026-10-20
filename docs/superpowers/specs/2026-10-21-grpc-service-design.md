# gRPC reference service — a polyglot boundary over the engine

**Status:** design (CTO-decided; owner delegated, "ưu tiên số 1, nhưng code luôn" 2026-10-21) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Enterprise readiness **Tier 3** (ecosystem), **item 1 of 3** — reference service + polyglot thin-clients. The last roadmap item. First slice of a larger subsystem.

## Intent and the why

Application teams in Java, Go, and PHP must consume LabJury without touching Python.
The settled design is a **stateless gRPC service** wrapping the engine, with **thin
clients generated from a `.proto`** — in-process plugin extension stays Python-only
(a gRPC boundary avoids cross-language FFI). The `.proto` is the real deliverable:
it is the single contract every language generates from.

This environment has the grpc/protobuf **runtimes** but not `grpc_tools` (protoc), so
`.proto` → stubs cannot be compiled here. That cleanly separates what is *code we own
and test* from what is *generated/transport glue*:

- **Owned & unit-tested (pure Python, zero-dep):** the domain↔wire translation and the
  engine-orchestration handler — the only places a bug would change a decision.
- **The contract:** the versioned `labjury/v1/labjury.proto`.
- **Generated / transport glue (documented, not unit-tested here):** the Python
  `*_pb2`/`*_pb2_grpc` stubs and the `grpc.aio` server binding (need protoc + a running
  server); the Java/Go/PHP clients (`protoc` from the same `.proto`, their build
  toolchains).

Core stays zero-dependency: everything lives under `labjury.service`, which
`import labjury` never imports; only the server binding imports grpc, lazily.

## Goals

- **`proto/labjury/v1/labjury.proto`** — the service contract:
  - `service LabJuryService { rpc Decide(DecideRequest) returns (DecideResponse); rpc DecideBatch(DecideBatchRequest) returns (DecideBatchResponse); }`
  - `Item { string id = 1; google.protobuf.Struct raw = 2; string tenant = 3; }`
  - `enum Status { STATUS_UNSPECIFIED; STATUS_DECIDED; STATUS_REVIEW; STATUS_FAILED; STATUS_RETRY_LATER; }`
  - `enum Action { ACTION_UNSPECIFIED; ACTION_ACCEPT; ACTION_BLOCK; ACTION_REVIEW; }`
    (prefixed value names — proto3 enum values share file scope, so `REVIEW` can't appear in two enums).
  - `Verdict { Action action; repeated string labels; map<string,double> scores; repeated string novel_labels; string reason; }`
  - `DecideResponse { string correlation_id; Status status; Verdict verdict; string error; double latency_ms; string tenant; }`
  - `DecideBatchRequest { repeated Item items; }` / `DecideBatchResponse { repeated DecideResponse results; }`
- **`labjury/service/translation.py`** (pure, zero-dep) — domain ↔ wire, proto-agnostic (works on plain Python values; emits the proto enum *names* as strings so the mapping is testable without compiled enums):
  - `item_from_wire(correlation_id: str, raw: dict, tenant: str | None) -> Item` (`tenant=""`→`None`).
  - `result_to_wire(result: ItemResult) -> dict` → `{correlation_id, status, verdict|None, error, latency_ms, tenant}`, `status` the `STATUS_*` name, nested verdict `action` the `ACTION_*` name, empty string/`0.0` for absent `error`/`latency_ms`, `tenant` `""` when `None`.
- **`labjury/service/handler.py`** (pure, duck-typed engine) — `DecisionHandler(engine)`:
  - `async decide(correlation_id, raw, tenant) -> dict` = `result_to_wire(await engine.process(item_from_wire(...)))`.
  - `async decide_batch(items: list[tuple[str, dict, str | None]]) -> list[dict]` via `engine.process_batch`.
- **`labjury/service/server.py`** (needs `[grpc]` + generated stubs; imports both **lazily inside `serve`**) — `serve(engine, address="[::]:50051")`: builds a `grpc.aio` server whose generated `LabJuryServiceServicer` subclass delegates to `DecisionHandler`, converting `Struct`↔dict and enum-name↔enum-int at the edge. Raises a clear error if grpc/stubs are missing.
- **Codegen + packaging:** a `scripts/gen_proto.sh` running `python -m grpc_tools.protoc` into `src/labjury/service/v1/` (git-ignored generated stubs); a `[project.optional-dependencies] grpc` extra (`grpcio`, `grpcio-tools`, `protobuf`).
- **Docs:** `docs/service.md` — the contract, running the server, generating clients for Python/Java/Go/PHP, the stateless design; a bilingual README pointer.

## Non-goals / anti-goals

- **No change to the zero-dep core.** `labjury.service` is never imported by
  `import labjury`; only `server.py` imports grpc, lazily. Nothing here is re-exported
  from the top-level package, and `labjury.__all__` is unchanged.
- **No hand-written Java/Go/PHP clients.** They are `protoc`-generated from the
  `.proto`; the slice ships the contract and the commands, not generated code.
- **No committed generated stubs.** `*_pb2*.py` are build artifacts (git-ignored),
  produced by `scripts/gen_proto.sh`.
- **No REST/JSON gateway, no auth/TLS/interceptors, no streaming, no server-side
  batching policy.** The service is a thin stateless adapter; transport concerns
  (TLS, authn/z, rate limits, a REST gateway) are the deployer's deployment layer.
- **No state in the service.** Each RPC calls `engine.process`/`process_batch` and
  returns; the engine and its plugins hold what state there is.
- **Live-server / stub-dependent code is not unit-tested in this repo** (no protoc
  here); its logic is kept trivial and the tested handler carries the behavior.

## Constraints (inherited)

- Core `dependencies = []`; the service's grpc deps live only in the `[grpc]` extra;
  `translation.py`/`handler.py` are pure stdlib. Core never imports `labjury.service`.
- No public plugin contract change; `Engine.process`/`process_batch` consumed as-is.
- Proto enum value names are globally prefixed to avoid proto3 scope collisions.
- Python 3.11+. TDD for the pure layers; commit per task.

## The parts of the how, as decided

- **Why emit proto enum *names* from `translation.py`:** it makes the
  semantically-important status/action mapping unit-testable without compiled proto
  enums; the server does the trivial `Status.Value(name)`/`Action.Value(name)` at the
  edge.
- **Why `Struct` for `raw`:** `Item.raw` is arbitrary JSON-like data; `google.protobuf.Struct`
  carries it to any language without a bespoke schema. The server converts `Struct`↔dict;
  `translation` sees a plain dict.
- **Why the servicer is built inside `serve`:** it must subclass a generated class, so
  it cannot exist at import time without stubs; a lazy factory keeps `server.py`
  importable (and the module testable) with no grpc installed.
- **Versioning:** the proto package is `labjury.v1`; the service contract versions on
  its own `vN` axis, independent of `labjury.__version__` (documented in service.md).

## What's left to the builder

- Exact `grpc.aio` server construction (thread pool / max workers) in `serve` — standard
  boilerplate; the brief fixes the delegation and the edge conversions.
- The `scripts/gen_proto.sh` flags are standard `grpc_tools.protoc` invocation.

## Review focus (inputs the tests must pin)

- **`item_from_wire` maps id/raw/tenant**, and `tenant="" → None` — Task 1.
- **`result_to_wire` maps a decided verdict** (status/action names, labels, scores,
  novel_labels, reason) — Task 1.
- **`result_to_wire` of a FAILED result with no verdict** → `verdict None`, `error`
  populated, `status STATUS_FAILED` — Task 1.
- **`DecisionHandler.decide` runs the engine and returns the wire dict**; a no-verdict
  result round-trips to `verdict None` — Task 2.
- **`decide_batch` preserves per-item correlation and order** over `process_batch`
  — Task 2.
