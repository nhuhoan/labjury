# LabJury Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LabJury core — a plugin-driven, async decision engine that turns an item into a labeling/moderation verdict via a propose → score → confidence-gated decision pipeline, with no hard dependency on any specific model.

**Architecture:** An async `Engine` orchestrates per-item flow through registered plugins (ContextBuilder → Proposer → Scorer → DecisionPolicy → Sink). A capability-aware Router picks each item's path at runtime (e.g. image-only items skip the Proposer). Scoring mirrors Jev's typed questions (Choice/Score/Noul → Answer with confidence); Jev is just one future `Scorer`, and a mandatory `LLMJudgeScorer` fallback keeps the core runnable without it. State is an open, extensible multimodal container. Plugins register programmatically or via entry-points. The engine owns fast-processing mechanisms (async, batching, bounded concurrency, explicit backpressure) but no queue, storage, or scale.

**Tech Stack:** Python 3.11+ (asyncio, `asyncio.TaskGroup`), `importlib.metadata` entry-points, `pytest` + `pytest-asyncio`. No third-party runtime deps in the core.

**Spec:** `docs/superpowers/specs/2026-10-19-autolabel-framework-design.md`

## Global Constraints

- **Package name:** `labjury`; repo `github.com/nhuhoan/labjury`.
- **Language/runtime:** Python **3.11+**, asyncio throughout; no blocking calls on the hot path. *(Author's call: floor is 3.11 for `asyncio.TaskGroup`; spec said "Python, asyncio".)*
- **No hard dependency on Jev.** The core must run end-to-end with only `LLMJudgeScorer`. Nothing in the core may `import` a Jev client.
- **Core has no third-party runtime dependencies.** Plugins may; the core may not.
- **Plugins register without core changes** — programmatic `register()` plus entry-point discovery under groups `labjury.<kind>`.
- **The core owns no queue, storage, or scaling.** No Kafka, no DB, no autoscaling; no throughput promise.
- **`process_batch` contract (frozen public API):** results are **unordered**, each carries its item's `correlation_id`; **partial-failure-tolerant** (one bad item → a `FAILED` result, siblings unaffected); **explicit backpressure** (under saturation → a `RETRY_LATER` result, never block indefinitely).
- **Open-world taxonomy:** content matching no known label is emitted as a *novel-label* review, never silently dropped.
- **Recall-biased violations:** a violation question that is not confidently clean → `REVIEW`/hold, never `ACCEPT`.
- **Multimodal, extensible state:** modalities are a registry of strings, never a closed enum.

## Review Focus

Spec-implied failure modes most likely to bite; each is pinned by a test in the owning task.

1. **Violation with low scorer confidence** must yield `REVIEW` (hold), never `ACCEPT` — the core safety asymmetry (Task 7).
2. **Item matching no known label, no candidate scoring high** must emit a novel-label `REVIEW`, not silently drop (Task 7).
3. **`process_batch` under saturation** must return `RETRY_LATER` per affected item rather than block or drop (Task 11).
4. **A single failing item in a batch** must return `FAILED` for only that item; siblings still decided (Task 11).
5. **Image-only item (ASR/text empty)** must still find a route (visual-fast-path) instead of dead-ending in the Proposer (Task 6).

---

## File Structure

- `pyproject.toml` — package metadata, Python floor, entry-point groups, test extras.
- `src/labjury/__init__.py` — public API exports.
- `src/labjury/state.py` — `Item`, `Content`, `State`, content-type registry.
- `src/labjury/decisions.py` — `Question` types, `Answer`, `Candidate`.
- `src/labjury/results.py` — `Action`, `Status`, `Verdict`, `ItemResult`.
- `src/labjury/plugins.py` — plugin Protocols + capability declarations.
- `src/labjury/registry.py` — programmatic + entry-point plugin registry.
- `src/labjury/router.py` — capability graph + per-item dynamic routing.
- `src/labjury/policies.py` — `RecallBiasedPolicy`.
- `src/labjury/taxonomy.py` — `InMemoryTaxonomyStore` (open-world lifecycle).
- `src/labjury/defaults.py` — `InMemoryCache`, `CollectingSink`.
- `src/labjury/scorers/llm_judge.py` — mandatory `LLMJudgeScorer` fallback.
- `src/labjury/observability.py` — `Observer` + `InMemoryObserver`.
- `src/labjury/engine.py` — `Engine.process` / `process_batch`.
- `tests/...` — one test module per source module.

---

### Task 1: Package scaffold + multimodal state

**Files:**
- Create: `pyproject.toml`, `src/labjury/__init__.py`, `src/labjury/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `register_content_type(name: str) -> None`, `is_content_type(name: str) -> bool`
  - `Content(modality: str, payload: Any, meta: dict | None = None)`
  - `State()` with `add(content: Content) -> None`, `get(modality: str) -> list[Content]`, `has(modality: str) -> bool`, `modalities() -> set[str]`, and a mutable `flags: set[str]` (routing signals live here, e.g. `"needs_semantic"`)
  - `Item(id: str, raw: Any, meta: dict | None = None)` — `id` is the `correlation_id`
  - Built-in registered modalities: `"text"`, `"json"`, `"image"`, `"audio"`, `"metadata"`, `"frame_sequence"`

- [ ] **Step 1: Write failing tests**

```python
def test_builtin_modalities_registered():
    for m in ["text", "json", "image", "audio", "metadata", "frame_sequence"]:
        assert is_content_type(m)

def test_register_new_content_type_without_core_change():
    register_content_type("heatmap")
    assert is_content_type("heatmap")

def test_content_with_unregistered_modality_raises():
    with pytest.raises(ValueError):
        Content("not_a_real_type", payload=b"")

def test_state_add_and_query():
    s = State()
    s.add(Content("text", "xin chào"))
    s.add(Content("image", b"\x89PNG"))
    assert s.has("text") and s.modalities() == {"text", "image"}
    assert s.get("text")[0].payload == "xin chào"
    assert s.get("audio") == []

def test_state_flags_mutable():
    s = State()
    s.flags.add("needs_semantic")
    assert "needs_semantic" in s.flags
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_state.py -v` → FAIL (imports missing)
- [ ] **Step 3: Implement `src/labjury/state.py`** — module-level content-type set seeded with the six built-ins; `Content.__post_init__` validates modality against the registry; `State` wraps a `list[Content]`. Add `pyproject.toml` (name `labjury`, `requires-python = ">=3.11"`, `src/` layout, optional `test` extra with `pytest`, `pytest-asyncio`) and export the names from `__init__.py`.
- [ ] **Step 4: Run tests, verify pass** — `pytest tests/test_state.py -v` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat: multimodal extensible state + package scaffold"`

---

### Task 2: Decision primitives (typed questions + answers)

**Files:**
- Create: `src/labjury/decisions.py`
- Test: `tests/test_decisions.py`

**Interfaces:**
- Produces:
  - `ChoiceQuestion(key: str, prompt: str, options: list[str])` — 1 ≤ len(options) ≤ 255
  - `ScoreQuestion(key: str, prompt: str, levels: list[str])` — 2 ≤ len(levels) ≤ 10
  - `NoulQuestion(key: str, prompt: str)`
  - `Question = ChoiceQuestion | ScoreQuestion | NoulQuestion`
  - `Answer(key: str, value: Any, confidence: float, distribution: dict[str, float] | None = None)` — 0.0 ≤ confidence ≤ 1.0
  - `Candidate(label: str, kind: str, question: Question)` — `kind` is a free string, e.g. `"tag"`, `"topic"`, `"violation"`

- [ ] **Step 1: Write failing tests**

```python
def test_choice_rejects_over_255_options():
    with pytest.raises(ValueError):
        ChoiceQuestion("topic", "which topic?", [f"o{i}" for i in range(256)])

def test_score_requires_2_to_10_levels():
    ScoreQuestion("quality", "how good?", ["low", "high"])         # ok
    with pytest.raises(ValueError):
        ScoreQuestion("quality", "how good?", ["only_one"])

def test_noul_question_constructs():
    assert NoulQuestion("is_violation", "violates policy?").key == "is_violation"

def test_answer_confidence_bounds():
    Answer("is_violation", value=False, confidence=0.9)           # ok
    with pytest.raises(ValueError):
        Answer("is_violation", value=False, confidence=1.5)

def test_candidate_wraps_question():
    c = Candidate("alcohol", "violation", NoulQuestion("alcohol", "promotes alcohol?"))
    assert c.kind == "violation" and c.question.key == "alcohol"
```

- [ ] **Step 2: Run tests, verify fail** — `pytest tests/test_decisions.py -v`
- [ ] **Step 3: Implement `src/labjury/decisions.py`** — dataclasses with `__post_init__` validation for the bounds above.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: typed decision primitives (Choice/Score/Noul + Answer + Candidate)"`

---

### Task 3: Result and verdict types

**Files:**
- Create: `src/labjury/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Produces:
  - `Action(Enum)`: `ACCEPT`, `BLOCK`, `REVIEW`
  - `Status(Enum)`: `DECIDED`, `REVIEW`, `FAILED`, `RETRY_LATER`
  - `Verdict(action: Action, labels: list[str], scores: dict[str, float], novel_labels: list[str], reason: str)`
  - `ItemResult(correlation_id: str, status: Status, verdict: Verdict | None = None, error: str | None = None)`

- [ ] **Step 1: Write failing tests**

```python
def test_item_result_carries_correlation_id():
    r = ItemResult("item-42", Status.DECIDED, verdict=Verdict(Action.ACCEPT, ["food"], {"food": 0.98}, [], "ok"))
    assert r.correlation_id == "item-42" and r.verdict.action is Action.ACCEPT

def test_retry_later_needs_no_verdict():
    r = ItemResult("item-7", Status.RETRY_LATER)
    assert r.verdict is None and r.status is Status.RETRY_LATER

def test_failed_carries_error():
    r = ItemResult("item-9", Status.FAILED, error="scorer timeout")
    assert r.error == "scorer timeout"
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/results.py`** — enums + dataclasses.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: verdict and item-result types with process_batch statuses"`

---

### Task 4: Plugin protocols + capability declarations

**Files:**
- Create: `src/labjury/plugins.py`
- Test: `tests/test_plugins.py`

**Interfaces:**
- Produces `@runtime_checkable Protocol`s. Each stage plugin exposes `accepts: frozenset[str]` (modalities it consumes; `frozenset({"*"})` = any):
  - `ContextBuilder`: `accepts`, `produces: frozenset[str]`, `async def build(item: Item, state: State) -> State`
  - `Proposer`: `accepts`, `async def propose(state: State) -> list[Candidate]`
  - `Scorer`: `accepts`, `async def score(state: State, questions: list[Question]) -> list[Answer]`
  - `DecisionPolicy`: `async def decide(state: State, candidates: list[Candidate], answers: list[Answer], taxonomy: "TaxonomyStore") -> Verdict`
  - `Sink`: `async def emit(result: ItemResult) -> None`
  - `TaxonomyStore`: `async def is_known(label: str) -> bool`, `async def propose(label: str, meta: dict | None = None) -> None`, `async def known_labels() -> set[str]`
  - `Cache`: `async def get(key: str) -> Verdict | None`, `async def put(key: str, verdict: Verdict) -> None`

- [ ] **Step 1: Write failing tests**

```python
def test_fake_scorer_satisfies_protocol():
    class FakeScorer:
        accepts = frozenset({"*"})
        async def score(self, state, questions): return []
    assert isinstance(FakeScorer(), Scorer)

def test_object_missing_method_is_not_scorer():
    class NotScorer:
        accepts = frozenset({"*"})
    assert not isinstance(NotScorer(), Scorer)

def test_capabilities_readable():
    class ImageOnly:
        accepts = frozenset({"image"})
        async def score(self, state, questions): return []
    assert "image" in ImageOnly().accepts
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/plugins.py`** — `runtime_checkable` Protocols; `TaxonomyStore` referenced by `DecisionPolicy` lives in the same module to avoid cycles.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: plugin protocols with capability declarations"`

---

### Task 5: Plugin registry (programmatic + entry-points)

**Files:**
- Create: `src/labjury/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces:
  - `register(kind: str, name: str, factory: Callable[[], Any]) -> None`
  - `get(kind: str, name: str) -> Any` (calls the factory)
  - `available(kind: str) -> list[str]`
  - `load_entry_points(prefix: str = "labjury") -> None` — discovers groups `labjury.context_builders`, `labjury.proposers`, `labjury.scorers`, `labjury.policies`, `labjury.sinks`, `labjury.taxonomies`, `labjury.caches`
  - `clear() -> None` (test hygiene)

- [ ] **Step 1: Write failing tests**

```python
def test_register_and_get():
    clear()
    register("scorers", "fake", lambda: "SCORER")
    assert get("scorers", "fake") == "SCORER"
    assert "fake" in available("scorers")

def test_get_unknown_raises():
    clear()
    with pytest.raises(KeyError):
        get("scorers", "missing")

def test_load_entry_points_registers(monkeypatch):
    # monkeypatch importlib.metadata.entry_points to yield one fake EP in group "labjury.scorers"
    ...
    load_entry_points()
    assert "fake_ep" in available("scorers")
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/registry.py`** — module-level `dict[str, dict[str, Callable]]`; `load_entry_points` maps each `labjury.<kind>` group's entry points into the registry via `ep.load`.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: plugin registry with entry-point discovery"`

---

### Task 6: Router — capability graph + dynamic per-item routing

**Files:**
- Create: `src/labjury/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `State`, `Scorer`, `Proposer` (their `accepts` sets), `State.flags`.
- Produces:
  - `Route(use_proposer: bool, scorer: Scorer)`
  - `Router(proposers: list[Proposer], scorers: list[Scorer])` with `route(state: State) -> Route`
- Routing rule (pin via tests): pick the first `Scorer` whose `accepts` covers the state's modalities (or `"*"`). **Visual-fast-path:** if a scorer directly accepts the state's modalities, the state carries no `"text"` content, and `"needs_semantic"` is **not** in `state.flags` → `use_proposer=False`. Otherwise `use_proposer=True`. If no scorer matches, raise `NoRouteError`.

- [ ] **Step 1: Write failing tests**

```python
async def test_image_only_item_skips_proposer():
    s = State(); s.add(Content("image", b"img"))
    router = Router(proposers=[TextProposer()], scorers=[ImageScorer()])  # ImageScorer.accepts={"image"}
    route = router.route(s)
    assert route.use_proposer is False and route.scorer.__class__ is ImageScorer

async def test_needs_semantic_flag_forces_long_route():
    s = State(); s.add(Content("image", b"img")); s.flags.add("needs_semantic")
    route = Router([TextProposer()], [ImageScorer(), StarScorer()]).route(s)
    assert route.use_proposer is True

async def test_text_item_uses_proposer():
    s = State(); s.add(Content("text", "ẩn ý khó hiểu"))
    route = Router([TextProposer()], [StarScorer()]).route(s)  # StarScorer.accepts={"*"}
    assert route.use_proposer is True

async def test_no_matching_scorer_raises():
    s = State(); s.add(Content("audio", b"wav"))
    with pytest.raises(NoRouteError):
        Router([], [ImageScorer()]).route(s)
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/router.py`** per the routing rule above; define tiny test doubles (`ImageScorer`, `StarScorer`, `TextProposer`) in the test module.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: capability-aware per-item router with visual-fast-path"`

---

### Task 7: Recall-biased decision policy (safety + open-world)

**Files:**
- Create: `src/labjury/policies.py`
- Test: `tests/test_policies.py`

**Interfaces:**
- Consumes: `Candidate`, `Answer`, `TaxonomyStore`, `Verdict`, `Action`.
- Produces: `RecallBiasedPolicy(accept_threshold: float = 0.85, clean_threshold: float = 0.9)` implementing `DecisionPolicy`.
- Decision rule (pin via tests):
  - For any `kind == "violation"` candidate whose answer is not "confidently clean" (i.e. `not (value is False and confidence >= clean_threshold)`) → `Action.REVIEW`, reason names the violation. **(Review Focus #1.)**
  - Else, among non-violation candidates, accept those with `confidence >= accept_threshold`; collect labels.
  - Any accepted label not `is_known` in the taxonomy → call `taxonomy.propose(label)` and add to `novel_labels`.
  - If no violation and no candidate clears `accept_threshold` → `Action.REVIEW` with a novel-label reason. **(Review Focus #2.)**

- [ ] **Step 1: Write failing tests**

```python
async def test_unsure_violation_is_held():
    pol = RecallBiasedPolicy()
    cands = [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))]
    answers = [Answer("alcohol", value=False, confidence=0.4)]   # unsure it's clean
    v = await pol.decide(State(), cands, answers, InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW

async def test_confidently_clean_violation_passes():
    answers = [Answer("alcohol", value=False, confidence=0.97)]
    v = await RecallBiasedPolicy().decide(State(),
        [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))], answers, InMemoryTaxonomyStore())
    assert v.action is Action.ACCEPT

async def test_confident_violation_blocks():
    answers = [Answer("alcohol", value=True, confidence=0.95)]
    v = await RecallBiasedPolicy().decide(State(),
        [Candidate("alcohol", "violation", NoulQuestion("alcohol", "?"))], answers, InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW   # not confidently clean -> held

async def test_novel_label_routed_to_review_and_proposed():
    tax = InMemoryTaxonomyStore(); await tax_seed(tax, {"food"})
    cands = [Candidate("mukbang", "tag", ChoiceQuestion("t", "?", ["mukbang"]))]
    answers = [Answer("t", value="mukbang", confidence=0.95)]
    v = await RecallBiasedPolicy().decide(State(), cands, answers, tax)
    assert "mukbang" in v.novel_labels and await tax.is_known("mukbang") is False  # proposed, not yet official

async def test_all_low_confidence_goes_to_review():
    cands = [Candidate("food", "tag", ChoiceQuestion("t", "?", ["food"]))]
    answers = [Answer("t", value="food", confidence=0.3)]
    v = await RecallBiasedPolicy().decide(State(), cands, answers, InMemoryTaxonomyStore())
    assert v.action is Action.REVIEW
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/policies.py`** per the rule above. (Task 8 provides `InMemoryTaxonomyStore`; if implementing Task 7 first, stub a minimal one in the test.)
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: recall-biased, open-world decision policy"`

---

### Task 8: Default taxonomy, cache, sink

**Files:**
- Create: `src/labjury/taxonomy.py`, `src/labjury/defaults.py`
- Test: `tests/test_taxonomy.py`, `tests/test_defaults.py`

**Interfaces:**
- Produces:
  - `InMemoryTaxonomyStore()` implementing `TaxonomyStore`, plus `async def promote(label: str) -> None` (proposed → official) and `async def proposed_labels() -> set[str]`. `is_known` is True only after `promote`.
  - `InMemoryCache()` implementing `Cache`.
  - `CollectingSink()` implementing `Sink`, exposing `results: list[ItemResult]`.

- [ ] **Step 1: Write failing tests**

```python
async def test_taxonomy_open_world_lifecycle():
    tax = InMemoryTaxonomyStore()
    assert await tax.is_known("asmr") is False
    await tax.propose("asmr")
    assert "asmr" in await tax.proposed_labels() and await tax.is_known("asmr") is False
    await tax.promote("asmr")
    assert await tax.is_known("asmr") is True

async def test_cache_round_trip():
    c = InMemoryCache()
    assert await c.get("h1") is None
    v = Verdict(Action.ACCEPT, ["food"], {"food": 0.9}, [], "ok")
    await c.put("h1", v)
    assert (await c.get("h1")).labels == ["food"]

async def test_sink_collects():
    s = CollectingSink()
    await s.emit(ItemResult("i1", Status.DECIDED))
    assert s.results[0].correlation_id == "i1"
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** both modules with plain dicts/lists/sets.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: in-memory taxonomy, cache, and collecting sink"`

---

### Task 9: LLM-as-judge fallback scorer (mandatory)

**Files:**
- Create: `src/labjury/scorers/__init__.py`, `src/labjury/scorers/llm_judge.py`
- Test: `tests/test_llm_judge.py`

**Interfaces:**
- Consumes: `Question` types, `Answer`, `State`.
- Produces: `LLMJudgeScorer(chat: Callable[[str], Awaitable[str]])` implementing `Scorer` with `accepts = frozenset({"*"})`. `chat` is an injected async callable that takes a prompt and returns a JSON string `{"value": ..., "confidence": ...}`; the scorer builds one prompt per question (rendering Choice options / Score levels / Noul yes-no), awaits `chat`, and parses into `Answer`. Must not import any model SDK.

- [ ] **Step 1: Write failing tests**

```python
async def test_scores_each_question_type_via_injected_chat():
    async def fake_chat(prompt: str) -> str:
        if "promotes alcohol" in prompt: return '{"value": true, "confidence": 0.92}'
        return '{"value": "food", "confidence": 0.8}'
    scorer = LLMJudgeScorer(chat=fake_chat)
    qs = [NoulQuestion("alcohol", "promotes alcohol?"), ChoiceQuestion("t", "topic?", ["food", "tech"])]
    answers = await scorer.score(State(), qs)
    by_key = {a.key: a for a in answers}
    assert by_key["alcohol"].value is True and by_key["alcohol"].confidence == 0.92
    assert by_key["t"].value == "food"

async def test_runs_with_no_jev_import():
    import sys
    scorer = LLMJudgeScorer(chat=lambda p: _async_return('{"value": false, "confidence": 0.5}'))
    assert isinstance(scorer, Scorer)
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `llm_judge.py`** — per-question prompt rendering + `json.loads` into `Answer`; one `chat` call per question (batching is a later optimization, not required here).
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: mandatory LLM-as-judge fallback scorer"`

---

### Task 10: Observability hooks

**Files:**
- Create: `src/labjury/observability.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Produces:
  - `Observer` Protocol: `on_decided(result: ItemResult) -> None`, `on_review(result: ItemResult) -> None`, `on_failed(result: ItemResult) -> None`, `on_retry_later(result: ItemResult) -> None`
  - `InMemoryObserver()` with counters `decided`, `review`, `failed`, `retry_later` and `review_rate() -> float`

- [ ] **Step 1: Write failing tests**

```python
def test_counters_and_review_rate():
    obs = InMemoryObserver()
    obs.on_decided(ItemResult("a", Status.DECIDED))
    obs.on_review(ItemResult("b", Status.REVIEW))
    obs.on_review(ItemResult("c", Status.REVIEW))
    assert obs.decided == 1 and obs.review == 2
    assert obs.review_rate() == pytest.approx(2 / 3)
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/observability.py`.**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: observability counters and hooks"`

---

### Task 11: Engine — orchestration, batching, backpressure, partial failure

**Files:**
- Create: `src/labjury/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Engine(context_builders: list[ContextBuilder], proposers: list[Proposer], scorers: list[Scorer], policy: DecisionPolicy, sink: Sink, cache: Cache, taxonomy: TaxonomyStore, observer: Observer, *, standing_candidates: list[Candidate] | None = None, max_concurrency: int = 64, cache_key: Callable[[Item], str] | None = None)`
  - `async def process(item: Item) -> ItemResult`
  - `async def process_batch(items: list[Item]) -> list[ItemResult]`
- Behaviour (pin via tests):
  - `process` flow: cache lookup (hit → `DECIDED` from cached verdict, skip expensive stages); else run context builders → `Router.route` → build the candidate set → `route.scorer.score(state, [c.question for c in candidates])` → `policy.decide` → cache put → map `Verdict.action` to `Status` (`REVIEW` → `Status.REVIEW`, else `DECIDED`) → `sink.emit` → observer hook → return result (always carrying `item.id`).
  - **Candidate set:** if `route.use_proposer`, `candidates = await proposer.propose(state)` plus any `standing_candidates`; on the visual-fast-path (`use_proposer=False`), `candidates = standing_candidates` (the always-asked policy checks — this is what the Jev image-scorer scores without a Proposer). If the fast path has no `standing_candidates`, that item is a misconfiguration → `ItemResult(id, FAILED, error="no candidates on fast path")`.
  - `process_batch`: run items concurrently under a bounded semaphore; **unordered** results; a per-item exception → `ItemResult(id, FAILED, error=...)` without cancelling siblings (`asyncio.TaskGroup` must not abort the group on one failure — gather per-item results individually). **(Review Focus #4.)**
  - **Backpressure:** if the concurrency budget is exhausted at admission (semaphore cannot be acquired without waiting beyond a zero/`try`-acquire), return `ItemResult(id, RETRY_LATER)` for the un-admitted items rather than blocking. **(Review Focus #3.)**

- [ ] **Step 1: Write failing tests**

```python
async def test_end_to_end_accept(make_engine):
    eng = make_engine()  # fixture wires fakes: text context builder, proposer->["food"], scorer->conf 0.95
    r = await eng.process(Item("i1", raw={"text": "món ăn ngon"}))
    assert r.status is Status.DECIDED and r.verdict.action is Action.ACCEPT and r.correlation_id == "i1"

async def test_cache_hit_skips_expensive_stages(make_engine):
    eng, proposer = make_engine(track_proposer=True)
    await eng.cache.put(eng._key(Item("i1", {"text": "x"})), Verdict(Action.ACCEPT, ["food"], {}, [], "cached"))
    r = await eng.process(Item("i1", {"text": "x"}))
    assert r.verdict.reason == "cached" and proposer.calls == 0

async def test_batch_results_unordered_but_complete(make_engine):
    eng = make_engine()
    items = [Item(f"i{n}", {"text": "t"}) for n in range(5)]
    results = await eng.process_batch(items)
    assert {r.correlation_id for r in results} == {f"i{n}" for n in range(5)}

async def test_one_failing_item_does_not_fail_batch(make_engine):
    eng = make_engine(fail_on_id="i2")  # scorer raises for i2
    results = {r.correlation_id: r for r in await eng.process_batch([Item("i1", {"text":"t"}), Item("i2", {"text":"t"})])}
    assert results["i2"].status is Status.FAILED and results["i1"].status in (Status.DECIDED, Status.REVIEW)

async def test_saturation_returns_retry_later(make_engine):
    eng = make_engine(max_concurrency=1, slow_scorer=True)
    results = await eng.process_batch([Item(f"i{n}", {"text":"t"}) for n in range(4)])
    assert any(r.status is Status.RETRY_LATER for r in results)

async def test_visual_fast_path_scores_standing_candidates():
    # image-only item, image-capable scorer, no proposer; standing policy check "nudity"
    standing = [Candidate("nudity", "violation", NoulQuestion("nudity", "contains nudity?"))]
    eng = _image_engine(standing_candidates=standing, scorer=ImageScorer(answer=Answer("nudity", True, 0.95)))
    r = await eng.process(Item("v1", {"image": b"img"}))
    assert r.status is Status.REVIEW   # confident violation held, proposer never consulted

async def test_fast_path_without_standing_candidates_fails_item():
    eng = _image_engine(standing_candidates=None, scorer=ImageScorer(answer=None))
    r = await eng.process(Item("v2", {"image": b"img"}))
    assert r.status is Status.FAILED
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement `src/labjury/engine.py`** — default `cache_key` = sha256 over a stable serialization of `item.raw`; admission via `asyncio.Semaphore` with a non-blocking acquire path for backpressure; per-item work wrapped so exceptions become `FAILED`. Add the `make_engine` pytest fixture with fakes in the test module.
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** — `git commit -m "feat: async engine with batching, backpressure, partial-failure"`

---

### Task 12: Public API, entry-point wiring, end-to-end no-Jev smoke test

**Files:**
- Modify: `src/labjury/__init__.py`, `pyproject.toml`
- Create: `tests/test_public_api.py`, `README.md`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Produces: top-level exports (`Item`, `Content`, `State`, `register_content_type`, the `Question`/`Answer`/`Candidate` types, `Action`/`Status`/`Verdict`/`ItemResult`, all plugin Protocols, `register`/`get`/`available`/`load_entry_points`, `Router`, `RecallBiasedPolicy`, `InMemoryTaxonomyStore`, `InMemoryCache`, `CollectingSink`, `LLMJudgeScorer`, `InMemoryObserver`, `Engine`). Declare the seven `labjury.<kind>` entry-point groups in `pyproject.toml`.

- [ ] **Step 1: Write failing tests**

```python
def test_public_surface_importable():
    import labjury as lj
    for name in ["Engine", "Item", "State", "LLMJudgeScorer", "RecallBiasedPolicy", "register", "load_entry_points"]:
        assert hasattr(lj, name)

async def test_full_pipeline_runs_without_jev():
    import labjury as lj
    async def chat(prompt): return '{"value": "food", "confidence": 0.95}'
    eng = lj.Engine(
        context_builders=[_TextBuilder()], proposers=[_FoodProposer()],
        scorers=[lj.LLMJudgeScorer(chat=chat)], policy=lj.RecallBiasedPolicy(),
        sink=lj.CollectingSink(), cache=lj.InMemoryCache(),
        taxonomy=lj.InMemoryTaxonomyStore(), observer=lj.InMemoryObserver())
    r = await eng.process(lj.Item("i1", {"text": "món ăn ngon"}))
    assert r.status in (lj.Status.DECIDED, lj.Status.REVIEW)
```

- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement** — fill `__init__.py` exports; add `[project.entry-points."labjury.scorers"]` etc. groups to `pyproject.toml`; write a short `README.md` (what LabJury is, the propose→score→decide model, "runs without Jev").
- [ ] **Step 4: Run full suite** — `pytest -v` → all PASS
- [ ] **Step 5: Commit** — `git commit -m "feat: public API, entry-point groups, no-Jev end-to-end smoke test"`

---

## Notes for follow-up plans (separate, depend on this core)

This core (Plan 1) is **unchanged** by the 2026-10-19 multi-language
decision — the gRPC service wraps the same `Engine.process_batch` API.

- **Plan 2 — reference plugins.** Live **Jev `Scorer`** (verify real
  schema incl. image input; batch questions per request; rate-limit +
  retry), **Vietnamese LLM `Proposer`**, **ASR / OCR / frame-sampling
  `ContextBuilder`s**, a persistent **TaxonomyStore** and **Cache** (e.g.
  Redis), and the **short-video** and **ads** reference pipelines (ads:
  topic + policy-violation + interest/audience suggestion). Each ships as
  an installable package registering via entry-points.
- **Plan 3 — service + thin clients (§6.7).** A **gRPC server** (optional
  REST/JSON gateway) wrapping the `Engine`, a **Protobuf** schema mirroring
  `Item` / `State` / `Verdict` / `ItemResult` and the `process_batch`
  contract (unordered / partial-failure / retry-later), and generated
  **thin clients for Python, Java, Go, PHP**. Stateless service.
