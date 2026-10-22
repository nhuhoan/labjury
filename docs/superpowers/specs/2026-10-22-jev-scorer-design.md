# JevScorer — a multimodal decision-model Scorer (reference example)

**Status:** built 2026-10-22 — `examples/jev_scorer.py` +
`tests/test_jev_scorer_example.py` (15 tests, all green). Wire contract from
TypeSafe's published System One API docs (`https://docs.typesafe.ai/api/system-one`).
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-22
**Tier / step:** Post-roadmap extension. The flagship sibling of the Quyet
example ([2026-10-22-quyet-scorer-design.md](2026-10-22-quyet-scorer-design.md)),
and the framework's **worked multimodal adapter** — the concrete thing
[docs/multimodal.md](../../multimodal.md) points to for "per-model image
serialization is yours, not the core's."

## Intent and the why

Jev ("System One", `POST https://api.typesafe.ai/v1/systemone`) is a calibrated
decision model — it reads a state and typed questions and returns calibrated
options, verbatim the LabJury `Scorer` contract. Quyet is its text-only sibling;
**Jev also takes images**, so this example exists to show the one thing Quyet
cannot: moving an image across the trust boundary to a remote model through the
`Scorer` seam. It lives in `examples/`, not the shipped package, for exactly the
reasons the Quyet doc lays out — the framework ships the interface, not vendor
glue.

## The model's wire contract (from TypeSafe's API docs)

- `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <key>`.
- Body: `{"model", "state", "questions", "assets"?}`. **`state` is a bare
  string** (for text) — *not* wrapped like Quyet's `{"message": …}`.
- **Images** go in `assets`, base64-inline:
  `{"<name>": {"type":"image","format":"png","data_base64":"…"}}`, and require
  the header `TypeSafe-Danger-Zone-Images: true`.
- Question types `noul` / `choice` / `score` line up 1:1 with LabJury, plus a
  `box` type (image localization → a normalized bounding box) that LabJury has
  **no question primitive** for.
- Response: `answers` keyed by question key; `usage:{input_tokens,output_tokens}`.
  Answer shapes are **identical to Quyet**: `choice{choice,confidence,
  probabilities}`, `score{score,confidence,legend,probabilities}`,
  `noul{noul}` (P(true), no confidence). No documented `partial_failures`.

## Goals — `examples/jev_scorer.py` → `JevScorer`

- `accepts = frozenset({"text", "image"})` — the multimodal declaration; the
  engine routes images here, a text-only scorer never sees them.
- Constructor mirrors Quyet exactly:
  `JevScorer(transport, *, model="jev-latest", cost_meter=None, tenant=None)`,
  `transport: Callable[[dict], Awaitable[dict]]`. A lazy `httpx_transport`
  factory ships alongside.
- **Request mapping** — `state` = joined text pieces (bare string). Each
  `Content("image", …)` → one base64-inline asset keyed `image_0`, `image_1`, …;
  `format` from `meta["format"]` or the subtype of `meta["mime"]` (default
  `png`); `bytes` payloads are base64-encoded, a `str` payload is assumed
  already-encoded. Questions map as in Quyet (choice criteria `{opt: null}`,
  score criteria = ordered levels, noul no criteria).
- **The image opt-in header is the transport's job**, not the scorer's: the
  scorer only adds `assets` to the body; `httpx_transport` sets
  `TypeSafe-Danger-Zone-Images: true` **iff** the body carries assets. This keeps
  the scorer wire-agnostic and testable with a plain fake.
- **Response mapping — identical calibrated rules to Quyet** (CTO-decided there):
  choice echoes value + probabilities; score takes `legend[argmax(probabilities)]`
  (the mode, *not* the continuous `score`) and re-keys the distribution by level;
  noul thresholds at 0.5 with `confidence = max(noul, 1-noul)`, documented as
  derived. Value validated ∈ options/levels.
- **Fail-closed**: a question key missing from `answers` raises
  `JevMissingAnswer(keys=[…])`. Jev validates up front (HTTP 422), so a 2xx with a
  missing key is unexpected — but a missing judgment must surface, never be
  fabricated.

## Non-goals / anti-goals

- **Not shipped in the package.** `examples/` now; a separate `labjury-jev`
  package (vendor-owned where possible) when there is install demand.
- **No `box` question.** Image localization returns a bounding box; LabJury has
  no `BoxQuestion` primitive and the engine's `Answer` is a typed label, not a
  region. Adding one is a *framework* decision (a new question/answer type),
  deliberately out of scope for an adapter example — call it out, don't smuggle
  a fourth question type into an example.
- **No multipart upload path.** The docs offer base64-inline *and* multipart;
  base64-inline is the one honest path an example needs. Multipart is a transport
  optimization for large images, left to a real package.
- **No pricing table, no forced HTTP dep, no batching/streaming**, same as Quyet.
- **No contract changes** to `Scorer`, `State`, `Answer`, or the engine.

## Review focus (tests pin)

- Text round-trip: `state` is a bare string; no `assets` key when there are no
  images; question criteria shaped per type.
- Image path: `bytes` → base64 asset with `format` derived from `mime`; explicit
  `meta["format"]` wins; a `str` payload passes through unencoded; multiple
  images index as `image_0…n`; `meta=None` tolerated.
- Calibrated mapping (choice/score-argmax/noul-threshold) mirrors Quyet's tests.
- Missing answer → `JevMissingAnswer` with the absent keys; no fabricated answer.
- `cost_meter` records once per call; `accepts == {"text","image"}`;
  empty state (no text, no image) raises; `isinstance(JevScorer(...), Scorer)`.

## Left to the builder

- Whether to add a framework-level `BoxQuestion`/region answer (separate design,
  not this example) if image localization becomes a real need.
- Multipart transport for large images, in a real `labjury-jev` package.
