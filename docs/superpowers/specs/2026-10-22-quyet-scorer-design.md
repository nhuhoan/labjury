# QuyetScorer — a calibrated decision-model Scorer (reference example)

**Status:** built 2026-10-22 — `examples/quyet_scorer.py` + `tests/test_quyet_scorer_example.py`
(14 tests, all green); the response mapping was pinned against the authoritative
marketplace sample (`score` returns `legend` index→level + `probabilities`;
`noul` returns P(true) only). **Scope
revised 2026-10-22:** adapters are *not* shipped in the framework package — they
live in `examples/` (illustrative, unpublished) now, and graduate to their own
`pip` package (`labjury-<model>`, ideally vendor-owned) only when there is real
install demand. The framework ships the `Scorer` interface, not per-vendor glue.
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-22
**Tier / step:** Post-roadmap extension. A worked reference for the decision-
model `Scorer` shape (the `labjury.contrib.jev` import in the docs is
illustrative and was never shipped). Quyet is one instance; Jev is the flagship
sibling, pending its wire contract.

## Intent and the why

Quyet-1.0-Large is a calibrated decision model (FPT Cloud marketplace,
`chinhnc/quyet-1.0-large`, fine-tuned from Gemma-4-31B-it). Per its own card:
*"Instead of generating text, it reads a state and a typed question, and
returns one option with calibrated probabilities."* That is, **verbatim, the
LabJury `Scorer` contract** — `decisions.py` even documents itself as
"mirroring Jev's question/answer model," and Quyet's three question `type`s
(`choice`, `noul`, `score`) line up 1:1 with `ChoiceQuestion` /
`NoulQuestion` / `ScoreQuestion`. So this is **structure mapping, not
semantic translation**: a thin, honest adapter.

It lives in **`examples/`, not the shipped package** — deliberately. The
framework already ships the universal `Scorer` interface and one generic in-core
scorer (`LLMJudgeScorer`, no provider import); its product is the contract plus
the pipeline, not per-vendor glue. Bundling a vendor adapter into core/contrib
would couple the framework to that vendor's API churn and read as favoritism.
An `examples/` reference teaches the shape without the framework owning the
churn; a real installable `labjury-quyet` package (vendor-owned where possible)
comes later, listed in a docs "Ecosystem" section — which serves the model
*better* than burying it in core, because adoption comes from a neutral
framework whose repo stays clean.

## The model's wire contract (observed, authoritative)

- `GET /v1/models` → `modality: "text->text"`, `input_modalities: ["text"]`,
  `output_modalities: ["text"]`, `context_length: 10000`,
  `max_completion_tokens: 1`, pricing `prompt $0.00000008/token`,
  `completion/image $0`. **Text-only; no image input.**
- `POST https://mkp-api.fptcloud.com/v1/systemone`,
  `Authorization: Bearer <key>`, body:
  ```json
  {"model":"Quyet-1.0-Large",
   "state":{"message":"<text>"},
   "questions":{"<key>":{"type":"choice|noul|score","instructions":"<prompt>","criteria":<...>}}}
  ```
- Response: `answers` keyed by question key, plus `partial_failures` and
  `usage:{input_tokens,output_tokens,total_tokens}`.

## Goals

**`examples/quyet_scorer.py` → `QuyetScorer`** — implements the `Scorer`
protocol (`accepts: frozenset[str]`,
`async def score(state, questions) -> list[Answer]`); not part of the shipped
package.

- `accepts = frozenset({"text"})` — confirmed by `input_modalities: ["text"]`,
  not a guess. (JSON/conversation states are text payloads; left to a later
  slice if ever needed.)
- **Constructor (dependency-injected, keeps the class zero-dep and testable):**
  ```python
  QuyetScorer(transport, *, model="Quyet-1.0-Large",
              cost_meter=None, tenant=None)
  ```
  `transport: Callable[[dict], Awaitable[dict]]` takes the request body and
  returns parsed JSON — exactly as `LLMJudgeScorer` injects `chat`. The
  deployer owns HTTP + auth; tests pass a fake. A thin optional
  `httpx_transport(api_key, base_url=...)` factory ships in the same module
  behind a lazy import (like `redis_cache` imports `redis` lazily) so the
  turnkey path is one line without forcing the dependency on importers.

### Request mapping (LabJury Question → Quyet question)

| LabJury | Quyet `questions[key]` |
|---|---|
| `ChoiceQuestion(prompt, options)` | `{"type":"choice","instructions":prompt,"criteria":{opt: null …}}` |
| `ScoreQuestion(prompt, levels)` | `{"type":"score","instructions":prompt,"criteria":levels}` (ordered list) |
| `NoulQuestion(prompt)` | `{"type":"noul","instructions":prompt}` |

`state.message` = the text pieces of `State` joined (same source
`LLMJudgeScorer._render` reads: `state.get("text")` → `piece.payload`). If the
joined text is empty, raise (nothing to judge). `context_length` is 10 000
tokens — oversized state is the deployer's concern for now; see non-goals.

### Response mapping (Quyet answer → `Answer`), **CTO-decided**

- **choice** → `Answer(key, value=a["choice"], confidence=a["confidence"],
  distribution=a["probabilities"])`. Validate `value ∈ question.options`
  (raise otherwise, as `LLMJudgeScorer` does).
- **score** → `value = legend[argmax(probabilities)]`;
  `confidence = a["confidence"]` (Quyet's own);
  `distribution = {legend[k]: p}`. Validate `value ∈ question.levels`.
  *Why argmax, not the continuous `score`:* the model's value proposition is
  calibrated probabilities; argmax of that distribution is the mode (optimal
  under 0-1 loss) and is **consistent with how `choice` is handled**. The
  continuous `score` is preserved in the distribution/meta for anyone who
  wants an ordinal-expected reading; it does not drive `value`.
- **noul** → `value = (a["noul"] >= 0.5)`;
  `confidence = max(noul, 1 - noul)`;
  `distribution = {"true": noul, "false": 1 - noul}`.
  *Why:* Quyet returns `noul` as P(true) with **no** confidence field. 0.5 is
  the only sensible decision threshold for a calibrated binary; confidence is
  the probability mass on the chosen side (consistent with choice, where
  Quyet's confidence tracks the top probability). **The derivation is
  documented as derived — we never pretend Quyet returned a confidence.**

### Failures — **fail-closed**

If a question key lands in `partial_failures` (absent from `answers`), raise
`QuyetPartialFailure(keys=[…])`. A **missing** judgment in a gating/labeling
system must surface, never be fabricated as a low-confidence answer that then
flows into block/hold. This composes with the existing `ReliableScorer`
(retry/fallback) — a deployer who wants degraded mode catches it themselves.

### Cost metering

If a `cost_meter` is injected, after each call
`cost_meter.record(tokens_in=usage["input_tokens"],
tokens_out=usage["output_tokens"], tenant=tenant)`. Reuses the shipped
`labjury.cost.CostMeter` side channel; no new contract. (Decision models
report `output_tokens: 0`; input is metered. Deployer supplies the $0.08/1M
rate to `TokenUsage.cost`.)

## Non-goals / anti-goals

- **Not shipped in the package.** Vendor adapter → `examples/`, then a separate
  `labjury-quyet` package when there is install demand. Never core/contrib.
- **No image / multimodal.** Quyet is text-only (`input_modalities: ["text"]`).
  Jev's image support is a **separate** follow-up on the Jev example, not this
  slice. The framework's multimodal support is already complete and tested
  (`State` modalities, `accepts` routing, strict-mode redaction coverage) — see
  [docs/multimodal.md](../../multimodal.md); no framework code is needed for it.
- **No pricing table.** Rates stay the deployer's (via `CostMeter`/`TokenUsage`).
- **No forced HTTP dependency.** Transport is injected; the `httpx` factory is
  an optional convenience, lazily imported.
- **No batching / streaming / state-truncation** in v1. One `POST` per
  `score()` call carrying all questions (the API already takes many questions
  at once). Oversized-state handling and batching are later optimizations.
- **No contract changes** to `Scorer`, `State`, `Answer`, or the engine.

## Constraints (inherited)

- Python 3.11+. Lives in `examples/quyet_scorer.py` (not packaged, not imported
  by core). TDD; commit per task.
- `QuyetScorer` itself imports no third-party package (transport injected);
  only the optional `httpx_transport` factory touches `httpx`, lazily.
- Public plugin contract unchanged — satisfies the `Scorer` `Protocol` by
  structure (`runtime_checkable`).

## Review focus (tests must pin)

- Each question type maps request-side correctly (choice criteria dict, score
  criteria list, noul no-criteria); multi-question request round-trips.
- **noul**: `0.73 → (True, conf 0.73)`; `0.20 → (False, conf 0.80)`;
  `0.50 → (True, conf 0.50)` boundary; distribution sums to 1.
- **score**: argmax picks the mode even when the continuous `score` would
  round elsewhere; `value ∈ levels`; distribution re-keyed by level.
- **choice**: `value` echoes `choice`; `value ∉ options` → raises.
- **partial_failures** non-empty → `QuyetPartialFailure` with the failed keys;
  no fabricated answer emitted.
- Returned list is **aligned to the input `questions` order**.
- `cost_meter` injected → `record` called once with the response's
  `input_tokens`/`output_tokens` and the scorer's `tenant`; absent meter → no
  error, no metering.
- `accepts == frozenset({"text"})`; empty text state → raises.
- `isinstance(QuyetScorer(fake), Scorer)` is `True`.

## Left to the builder

- Exact `transport` fake shape in tests (dict-in/dict-out async callable).
- Whether `tenant` is constructor-fixed (chosen here) or read from
  `state` metadata — constructor-fixed for v1; `State` carries no tenant today
  (same stance as the metered-cost doc).
- Text-join separator for multi-piece state (newline, proposed).
