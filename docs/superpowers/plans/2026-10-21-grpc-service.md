# gRPC Reference Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the LabJury gRPC service contract (`.proto`) and its tested, pure-Python core — the domain↔wire translation and the engine-orchestration handler — plus a lazy-wired reference server, a codegen script, the `[grpc]` extra, and docs; all without touching the zero-dependency core.

**Architecture:** `labjury.service` is an optional subpackage never imported by `import labjury`. `translation.py` and `handler.py` are pure stdlib and fully unit-tested (they hold the only logic that can change a decision). `server.py` imports grpc and the protoc-generated stubs lazily inside `serve()`, so the module imports with no grpc present. The `.proto` is the versioned polyglot contract (`labjury.v1`); thin clients for Java/Go/PHP are `protoc`-generated from it, not hand-written. The `[grpc]` extra carries grpcio/grpcio-tools/protobuf.

**Tech Stack:** Python 3.11+ (pure stdlib for the tested core); grpcio/protobuf behind the `[grpc]` extra; pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-grpc-service-design.md`

## Global Constraints

- Zero-dep core untouched: `import labjury` must not import `labjury.service`; nothing here is added to `labjury.__all__`; only `server.py` imports grpc, and only lazily inside `serve()`.
- `translation.py` and `handler.py` are pure stdlib (no grpc/protobuf import) so they test without the `[grpc]` extra.
- Proto enum value names are globally prefixed (`STATUS_*`, `ACTION_*`) — proto3 enum values share file scope.
- No committed generated stubs (git-ignored); no hand-written polyglot clients; no REST/auth/TLS/streaming.
- TDD for the pure layers; the stub-dependent server glue is kept trivial and is not unit-tested here (documented ruling).
- Commit per task.

## Review Focus

- `item_from_wire` maps id/raw/tenant and `tenant=="" → None` — pinned in Task 1 (`test_item_from_wire`, `test_empty_tenant_is_none`).
- `result_to_wire` maps a decided verdict (status/action names, labels, scores, novel_labels, reason) — pinned in Task 1 (`test_result_to_wire_decided`).
- `result_to_wire` of a FAILED/no-verdict result → verdict None, error set, STATUS_FAILED — pinned in Task 1 (`test_result_to_wire_failed`).
- `DecisionHandler.decide` runs the engine and returns the wire dict; no-verdict → verdict None — pinned in Task 2 (`test_handler_decide`, `test_handler_decide_failed`).
- `decide_batch` preserves correlation and order — pinned in Task 2 (`test_handler_decide_batch`).

---

### Task 1: The `.proto` contract + pure wire↔domain translation

**Files:**
- Create: `proto/labjury/v1/labjury.proto`
- Create: `src/labjury/service/__init__.py`
- Create: `src/labjury/service/translation.py`
- Test: `tests/test_service_translation.py`

**Interfaces:**
- Consumes: `Item` from `labjury.state`; `ItemResult`, `Verdict`, `Action`, `Status` from `labjury.results`.
- Produces:
  - `labjury.service.translation.item_from_wire(correlation_id: str, raw: dict, tenant: str | None) -> Item` — `Item(correlation_id, raw, tenant=tenant or None)`.
  - `labjury.service.translation.result_to_wire(result: ItemResult) -> dict` — `{"correlation_id", "status", "verdict", "error", "latency_ms", "tenant"}` where `status` is the `STATUS_*` name, `verdict` is `None` or `{"action": ACTION_* name, "labels": list, "scores": dict, "novel_labels": list, "reason": str}`, `error` is `result.error or ""`, `latency_ms` is `result.latency_ms or 0.0`, `tenant` is `result.tenant or ""`.
  - Module constants `_STATUS_TO_WIRE: dict[Status, str]`, `_ACTION_TO_WIRE: dict[Action, str]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_service_translation.py`

```python
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.service.translation import item_from_wire, result_to_wire


def test_item_from_wire():
    item = item_from_wire("i1", {"text": "x"}, "acme")
    assert item.id == "i1" and item.raw == {"text": "x"} and item.tenant == "acme"


def test_empty_tenant_is_none():
    assert item_from_wire("i1", {}, "").tenant is None


def test_result_to_wire_decided():
    v = Verdict(Action.BLOCK, ["nsfw"], {"nsfw": 0.9}, ["novel"], "bad")
    r = ItemResult("i1", Status.DECIDED, verdict=v, latency_ms=12.5, tenant="acme")
    w = result_to_wire(r)
    assert w["correlation_id"] == "i1"
    assert w["status"] == "STATUS_DECIDED"
    assert w["verdict"]["action"] == "ACTION_BLOCK"
    assert w["verdict"]["labels"] == ["nsfw"]
    assert w["verdict"]["scores"] == {"nsfw": 0.9}
    assert w["verdict"]["novel_labels"] == ["novel"]
    assert w["verdict"]["reason"] == "bad"
    assert w["latency_ms"] == 12.5 and w["tenant"] == "acme"


def test_result_to_wire_failed():
    r = ItemResult("i1", Status.FAILED, error="boom")
    w = result_to_wire(r)
    assert w["status"] == "STATUS_FAILED"
    assert w["verdict"] is None
    assert w["error"] == "boom"
    assert w["tenant"] == "" and w["latency_ms"] == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_translation.py -v`
Expected: FAIL — `No module named 'labjury.service'`.

- [ ] **Step 3: Create `proto/labjury/v1/labjury.proto`**

The contract from the spec (service, Item, Status, Action with prefixed values, Verdict, DecideRequest/Response, DecideBatchRequest/Response), `syntax = "proto3"`, `package labjury.v1`, `import "google/protobuf/struct.proto"`.

- [ ] **Step 4: Create `src/labjury/service/__init__.py` (empty) and `translation.py`**

`_STATUS_TO_WIRE` / `_ACTION_TO_WIRE` mapping each enum member to its `STATUS_*`/`ACTION_*` name; `item_from_wire` and `result_to_wire` per Interfaces, with a private `_verdict_to_wire`. Pure stdlib — no grpc/protobuf import.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_service_translation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proto/labjury/v1/labjury.proto src/labjury/service/__init__.py src/labjury/service/translation.py tests/test_service_translation.py
git commit -m "feat: gRPC service contract (.proto) + pure wire<->domain translation"
```

---

### Task 2: `DecisionHandler` — engine orchestration

**Files:**
- Create: `src/labjury/service/handler.py`
- Test: `tests/test_service_handler.py`

**Interfaces:**
- Consumes: `item_from_wire`, `result_to_wire` (Task 1); a duck-typed engine with `async process(item)` / `async process_batch(items)`.
- Produces: `labjury.service.handler.DecisionHandler(engine)`:
  - `async decide(self, correlation_id: str, raw: dict, tenant: str | None) -> dict`
  - `async decide_batch(self, items: list[tuple[str, dict, str | None]]) -> list[dict]`

- [ ] **Step 1: Write the failing tests** in `tests/test_service_handler.py`

```python
from labjury.results import Action, ItemResult, Status, Verdict
from labjury.service.handler import DecisionHandler


class _FakeEngine:
    def __init__(self, by_id):
        self._by_id = by_id
    async def process(self, item):
        return self._by_id[item.id]
    async def process_batch(self, items):
        return [self._by_id[i.id] for i in items]


def _decided(cid, labels):
    return ItemResult(cid, Status.DECIDED,
                      verdict=Verdict(Action.ACCEPT, labels, {}, [], "ok"))


async def test_handler_decide():
    eng = _FakeEngine({"i1": _decided("i1", ["spam"])})
    w = await DecisionHandler(eng).decide("i1", {"text": "x"}, "acme")
    assert w["correlation_id"] == "i1"
    assert w["status"] == "STATUS_DECIDED"
    assert w["verdict"]["labels"] == ["spam"]


async def test_handler_decide_failed():
    eng = _FakeEngine({"i1": ItemResult("i1", Status.FAILED, error="boom")})
    w = await DecisionHandler(eng).decide("i1", {}, None)
    assert w["verdict"] is None and w["error"] == "boom"


async def test_handler_decide_batch():
    eng = _FakeEngine({"i1": _decided("i1", ["a"]), "i2": _decided("i2", ["b"])})
    out = await DecisionHandler(eng).decide_batch([("i1", {}, None), ("i2", {}, "t")])
    assert [w["correlation_id"] for w in out] == ["i1", "i2"]
    assert out[1]["verdict"]["labels"] == ["b"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_service_handler.py -v`
Expected: FAIL — `No module named 'labjury.service.handler'`.

- [ ] **Step 3: Implement `src/labjury/service/handler.py`**

`DecisionHandler` per Interfaces: `decide` builds the item via `item_from_wire`, awaits `engine.process`, returns `result_to_wire`; `decide_batch` builds all items, awaits `engine.process_batch`, maps `result_to_wire`. Pure — no grpc import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_service_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite** (new subpackage must not perturb core)

Run: `pytest`
Expected: PASS; confirm `python -c "import labjury"` still needs no grpc (service not imported by the package init).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/service/handler.py tests/test_service_handler.py
git commit -m "feat: DecisionHandler — stateless engine orchestration for the service"
```

---

### Task 3: Reference server, codegen, packaging, docs

**Files:**
- Create: `src/labjury/service/server.py`
- Create: `scripts/gen_proto.sh`
- Modify: `pyproject.toml` (`[grpc]` extra), `.gitignore` (generated stubs)
- Create: `docs/service.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `DecisionHandler` (Task 2); grpc + generated stubs (lazy, inside `serve`).
- Produces: `labjury.service.server.serve(engine, address: str = "[::]:50051")` (async) — starts a `grpc.aio` server delegating to `DecisionHandler`; importing the module requires no grpc.

- [ ] **Step 1: Write the failing test** in `tests/test_service_handler.py` (or a new `tests/test_service_server.py`)

```python
def test_server_module_imports_without_grpc():
    # server.py must be importable with no grpc installed; grpc is lazy in serve()
    import importlib
    mod = importlib.import_module("labjury.service.server")
    assert hasattr(mod, "serve")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_service_server.py -v`
Expected: FAIL — `No module named 'labjury.service.server'`.

- [ ] **Step 3: Implement `src/labjury/service/server.py`**

Module level: only stdlib + `from labjury.service.handler import DecisionHandler`. `async def serve(engine, address="[::]:50051")`: inside, lazily `import grpc` and `from labjury.service.v1 import labjury_pb2, labjury_pb2_grpc` (raise a clear `RuntimeError` with the codegen command if the import fails); define a `_Servicer(labjury_pb2_grpc.LabJuryServiceServicer)` subclass whose `Decide`/`DecideBatch` convert `Struct`↔dict and enum-name↔int around a `DecisionHandler`; create a `grpc.aio.server()`, add the servicer, bind `address`, start, and `await server.wait_for_termination()`. Keep it minimal; it is reference glue.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_service_server.py -v`
Expected: PASS (module imports; `serve` not called).

- [ ] **Step 5: Codegen script, packaging, docs**

- `scripts/gen_proto.sh`: `python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src proto/labjury/v1/labjury.proto` (writes `src/labjury/service/v1/…` — note: adjust `--python_out` target to land under the package; document the exact paths).
- `.gitignore`: ignore generated `*_pb2.py` / `*_pb2_grpc.py` under `src/labjury/service/v1/`.
- `pyproject.toml`: add `grpc = ["grpcio>=1.60", "grpcio-tools>=1.60", "protobuf>=4"]` to `[project.optional-dependencies]`.
- `docs/service.md`: the contract overview; `pip install labjury[grpc]` + `bash scripts/gen_proto.sh`; running `asyncio.run(serve(engine))`; generating clients for Python/Java/Go/PHP from the same `.proto` (the `protoc` commands); the stateless design and the deployer-owned transport concerns (TLS/auth/REST gateway); proto versioning (`labjury.v1`). Add "### gRPC service & polyglot clients" to `README.md` and "### Service gRPC & client đa ngôn ngữ" to `README.vi.md` after the governance section, each linking the doc.

- [ ] **Step 6: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/labjury/service/server.py scripts/gen_proto.sh pyproject.toml .gitignore docs/service.md README.md README.vi.md tests/test_service_server.py
git commit -m "feat: reference gRPC server (lazy-wired), codegen script, [grpc] extra, docs"
```
