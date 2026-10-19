# LabJury — Design Document

*Date: 2026-10-19*
*Status: Draft for review*

> **Name:** **LabJury** (package `labjury`, repo `github.com/nhuhoan/labjury`).
> Chosen 2026-10-19 and verified clear on PyPI, GitHub, and web search.
> It is **LAB(EL) + JURY** — labeling plus the "jury" architecture
> (proposers plead, Jev judges, a verdict is rendered), and reads as the
> backronym **L**abeling **A**nd **B**atch **J**udgment **U**nder **R**anked
> **Y**ardsticks. Wherever this document says "the framework", it means
> LabJury.

## 1. Intent and the Why

The owner runs a large short-video platform. Every day it must classify
roughly **20M videos and 30M ads (~50M items/day)**: assign topic tags
and labels to videos, and for ads decide the topic, whether the ad
violates platform policy (block if so), and if clean, suggest interests
and audiences.

Today this is done by **human reviewers plus an image/OCR recognition
AI**. Both are failing:

- **Humans are overloaded** at this volume.
- **The current AI misses violating ads** (dangerous false negatives).
- **The taxonomy has gaps**: when content doesn't match any predefined
  label, the system silently skips it instead of flagging that something
  new appeared.
- **Vietnamese, slang, and implied/indirect meaning** are poorly
  understood.

The owner was drawn to **Jev** (TypeSafe AI's "System One" model, released
15 Sep 2026): a *discriminative, decision-only* model. It does not
generate text. You give it a "state" (text / JSON / **image** — see §6)
and a set of typed questions; it returns typed answers —
`Choice` (pick 1 of up to 255), `Score` (a point on an ordered verbal
scale), `Noul` (yes/no with probability 0–1) — each with a probability
distribution and a confidence value. Input ≈ $0.042/M tokens, **output
free**, latency 70–500ms, ~40–200× faster/cheaper than frontier LLMs for
this class of work. It is **proprietary, hosted API only, behind an
early-access waitlist, no on-prem, no public weights.**

The core architectural insight the whole framework rests on: **Jev is the
judge, not the author.** A generative step (usually an LLM) *proposes*
candidate labels; Jev *scores and confirms* them. The expensive
generative work runs sparingly; the high-volume repeated scoring runs on
Jev, which is near-free. This is what makes quality + safety + low cost
reconcilable at 50M/day.

## 2. What We Are Building

An **open-source Python framework** — the reusable *decision brain* plus a
*plugin system*. The short-video and ads use cases are implemented as
**real reference plugins** (not toy examples) to prove the framework.

The framework exposes an async callable engine (`process(item)` /
`process_batch(items)`) that an **external** worker — sitting behind the
owner's own Kafka / queue / orchestration — calls. The framework is
designed to be *easy to wire into* those systems but **does not own
them**.

**Multi-language consumption (decided 2026-10-19).** Research teams build
and configure pipelines/plugins in **Python**, but application teams use
**Java / Go / PHP** and must not be forced into Python. Resolution:
LabJury is **consumable as a service** — the Python engine runs behind a
language-neutral **gRPC (+ optional REST/JSON)** contract, and app teams
call it through **thin, generated client SDKs** in their own language. The
implementation language of a service is invisible to its callers, so this
delivers polyglot reach **without** reimplementing the engine in each
language. See §6.7.

## 3. Goals

- A clean plugin architecture: third parties ship `pip` packages that
  register plugins via entry-points, without modifying the core.
- Division of labor baked in: **cheap generative proposal → near-free Jev
  scoring → confidence-gated decision**.
- **Safety-first, recall-biased policy decisions**: for violations,
  "when in doubt, hold it," never "when unsure, let it pass."
- **Open-world taxonomy**: unknown content is flagged as a *proposed new
  label* and routed to review, never silently dropped. This feeds
  taxonomy growth.
- **Performance is a first-class property of the core** (async, batching,
  concurrency, backpressure, caching), so a single node performs well and
  scales horizontally cleanly.
- **No hard dependency on Jev.** Jev is one `Scorer` implementation; a
  fallback "LLM-as-judge" scorer must exist so contributors without Jev
  access can run the framework.
- **Multimodal, extensible state** from day one (text, JSON, image, audio,
  and future types) — the core never knows a closed set of modalities.

## 4. Non-Goals

- The framework does **not** provide Kafka, message queues, workers,
  cluster orchestration, autoscaling, or storage backends. It integrates
  with them through interfaces; the owner runs them externally.
- The framework does **not** own the **scaling problem**. It builds only
  the *processing mechanism* and the mechanisms that make it fast; reaching
  any particular throughput (e.g. 50M/day) is each enterprise's own
  architecture, built around the framework. The framework makes no
  throughput promise or scale SLA.
- The framework does **not** ship a human-review UI. It emits review
  requests and ingests review results through a clean contract; the UI is
  someone else's concern.
- The framework does **not** hardcode any specific LLM, ASR, OCR, cache,
  or database vendor. Those are plugins.

## 5. Anti-Goals (failure even if it technically works)

- A framework whose core architecture bottlenecks throughput, so no amount
  of added hardware helps. Performance-blindness is failure.
- A framework that stops working the moment Jev access is unavailable.
- A "closed-world" classifier that silently skips content it has no label
  for — repeating today's worst failure.
- Treating policy-violation detection as a symmetric "highest score wins"
  problem, letting violations through on low confidence.

## 6. Architecture — Decisions Made

All of the following are the **author's (CTO) design calls**, open to the
owner's correction.

### 6.1 Per-item pipeline (the brain)

The framework exposes async `process(item)` / `process_batch(items)`.
An external worker calls it. Internally an item flows through staged
plugin points:

1. **Context Builder** *(plugin, chainable)* — turns raw input into a
   rich multimodal **state**. For video: ASR (voice→text), OCR (text in
   image), hashtags, audio cues, sampled frames. The quality of this step
   is what fixes the Vietnamese / slang / implied-meaning problem — a
   richer state yields better judgments.
2. **Candidate Proposer** *(plugin)* — the generative step (typically a
   Vietnamese-strong LLM): "which labels / which violations might this
   be?" This is the **most expensive** stage, so a cache guards it (§6.4).
3. **Scorer** *(plugin — Jev lives here)* — receives the state + candidate
   list as typed questions (`Choice` / `Score` / `Noul`) and returns
   score + confidence. **Jev is one implementation of the `Scorer`
   interface; an LLM-as-judge fallback scorer is mandatory** so the
   framework never dies on Jev's proprietary/waitlisted API.
4. **Decision Policy** *(plugin)* — turns scores + confidence into an
   action. This is where "safe" is encoded: violations use a
   **recall-biased threshold** (unsure → hold); high confidence →
   auto-accept; low confidence or a novel label → route to review. The
   framework is **budget-agnostic**: it ships sane default thresholds but
   bakes in no human-routing budget or miss-rate SLA — the deployer tunes
   those. An optional **second automated arbitration stage** (e.g. a
   stronger model, or an ensemble, before falling back to humans) may be
   inserted as an extra policy/scorer plugin; it is **not** a mandatory
   stage.
5. **Sink / Router** *(plugin)* — where results go: accepted → label DB;
   uncertain → human review queue; novel label → taxonomy proposal. The
   framework emits events; external systems consume them.

### 6.2 Multimodal, extensible state

State is **not** a fixed enum of modalities. It is an **open, extensible
typed container** holding text, JSON, images/frames, audio, numeric
metadata (e.g. view/engagement counts), frame-sequences, and future
types. Adding a new input type = **registering a new content type**, never
a core rewrite.

**Capability negotiation:** each plugin **declares which modalities it
accepts**. The framework **assembles the pipeline from those
capabilities** rather than running a fixed linear chain. Consequence and
a further cost lever: *visual* violations (nudity, banned logos, graphic
imagery) can go **straight to a Jev image-scorer on sampled frames**,
skipping the expensive ASR→text→LLM path; only *semantic* cases (implied
meaning, slang) take the long route through the Proposer.

**Routing is dynamic per-item, not static per content-type** *(author's
call)*. Because the visual-fast-path must decide *per item* ("this one is
purely visual → skip ASR/LLM"), the engine is a per-item router with
branch conditions, and a plugin can **signal** that an item needs the
longer semantic route. The capability graph (which plugins *can* consume
which modalities) is resolved once at startup; the *path an individual
item takes through that graph* is decided at runtime from the item's
content. A static per-content-type router was considered and rejected
because it cannot express "this particular video is visual-only."

> Fact to verify in implementation: the owner states **Jev now accepts
> image input**. The author's research at design time found TypeSafe's
> published docs describing text/JSON only. The state container is designed
> to carry images regardless; the Jev plugin will verify the live schema
> before relying on image input.

### 6.3 Cross-cutting components

6. **Taxonomy Store** *(plugin)* — the label set, **open-world**, with a
   lifecycle: *proposed label → human review → official label*. This is
   what fixes "hits a gap, skips silently."
7. **Decision Cache** *(plugin, e.g. Redis)* — content hash / fingerprint
   → prior decision. Duplicate / near-duplicate content (re-run ads,
   re-uploaded clips, shared audio) skips the expensive stages entirely.
   The author's estimate is that this is a large fraction of 50M/day and a
   major cost lever; the exact ratio is unverified and to be measured.
8. **Human-in-the-loop contract** — not a UI, but a clean contract:
   *emit a review request* outward, *ingest a review result* back — so
   human decisions return to grow the taxonomy and tune thresholds.
   **The loop is fire-and-forget, keeping the brain stateless** *(author's
   call, to preserve the §4 "owns no storage" non-goal)*. An item routed to
   review is **terminated** with a review-request event carrying a
   correlation ID; the engine does **not** park and resume it. The human
   result arrives later as a *new* ingest — a taxonomy update and/or a
   re-submitted item — correlated by that ID. Threshold tuning from review
   results is therefore **offline/periodic** (the framework emits the data;
   retraining/retuning happens out of band), not an online in-engine loop.
   A park-and-resume model was rejected because it would force durable
   per-item state into the framework.
9. **Plugin Registry** — `register()` for all plugin types, via
   entry-points, so third parties ship `pip` packages and plug in without
   touching core.
10. **Observability** — hooks measuring cost, confidence, human-routing
    rate, and (crucially) the violation miss rate. "Quality" and "cheap"
    are only manageable if measured.

### 6.4 Integration model (how plugins reach models)

- **Two layers, kept distinct.** Framework ↔ plugin is a **Python async
  interface** (`async def propose(...)`, `async def score(...)`, etc.) —
  **not** a network protocol. The core is transport-agnostic and does not
  know or care whether a plugin is backed by HTTP, gRPC, or a local
  model.
- Plugin ↔ model is the plugin's own business, and in practice almost
  always **HTTP** under the hood. The meaningful distinction is **where
  the endpoint lives and who controls/pays for it**, not the protocol:
  - **Jev scorer**: TypeSafe's hosted REST API over HTTPS (only option
    today). The plugin must batch many questions per request, respect rate
    limits, and handle retry + backpressure.
  - **LLM proposer**: the plugin chooses — commercial API (Claude / GPT /
    Gemini) **or** a self-hosted open model (vLLM, Ollama). See §6.5.
  - **ASR / OCR context builders**: API or local, same freedom.

### 6.5 Cost posture at 50M/day

The Proposer (generative) is the cost driver; Jev is near-free. Design
stance: keep the Proposer interface open to a **self-hosted open model**
for bulk load, reserving commercial APIs for hard cases. Combined with the
decision cache (§6.4 #7) and the visual-fast-path (§6.2), the aim is to
run the expensive generative step on only the small "genuinely new and
semantically hard" slice of traffic.

### 6.6 Performance, baked into the core

Async throughout (no blocking calls; waiting on ASR or Jev is
non-blocking); **batching** at the Proposer and Scorer (Jev evaluates many
questions in parallel in one pass — the framework must exploit this);
bounded concurrency with **backpressure** (throttle when an upstream API
saturates, never self-DoS); cache in front of the expensive stage. A
single node must perform well; horizontal scale must be clean. The
framework makes scaling *possible*; pressing the button to 50M/day is the
external infrastructure's job.

**The framework owns fast-processing *mechanisms*, not throughput targets
or scale** *(author's call, per owner 2026-10-19)*. It provides the
mechanisms that let a unit of processing run fast — async, batching,
bounded concurrency, backpressure, caching — and nothing more. *How many
items/sec, how many nodes, what architecture reaches 50M/day* is each
enterprise's own scaling problem, built around the framework. The
framework makes **no throughput promise and no scale SLA.**

What it does fix is the `process_batch` **public-API contract**, because
that contract is the hinge integrators build their scaling on and
changing it later breaks everyone: results are **unordered** (each
carries its item's correlation ID, not list position),
**partial-failure-tolerant** (one bad item returns an error result rather
than failing the batch), and backpressure is **explicit** — under
saturation it returns a typed "retry-later" result instead of blocking
indefinitely, so an external worker can re-enqueue cleanly. Asyncio is the
baseline; multiprocessing/sharding is allowed but never required by the
core.

### 6.7 Multi-language access — service + thin clients

Two distinct boundaries, kept separate:

- **Plugin boundary (research tier):** stays a **Python in-process async
  interface** (§6.4). Plugins are Python; this keeps plugin calls fast and
  sits where research works. Polyglot *plugins* are explicitly **not**
  pursued — the FFI / per-plugin-RPC pain is not worth it given plugins
  are mostly thin wrappers over remote HTTP calls (Jev, LLM, ASR).
- **Consumer boundary (application tier):** a **language-neutral service
  contract**. The engine is wrapped by a server exposing **gRPC** (with an
  optional REST/JSON gateway). The `process_batch` contract (unordered /
  partial-failure / retry-later, §6.6) maps directly onto the gRPC API.
  The service is **stateless**, so it scales horizontally trivially and
  scaling remains the enterprise's concern (§4).
- **Thin clients:** generated from one Protobuf schema for **Python, Java,
  Go, PHP** — idiomatic, minimal, carrying no engine logic. An app calls
  `classify(item) -> verdict` in its own language and never touches Python.

Rejected alternatives: rewriting the engine natively per language (3–4×
cost, drift); a single Rust core with FFI bindings to Python/Java (async
across FFI + plugin callbacks across the boundary are too painful); WASM
component model (tooling immature for heavy workloads). The
service-with-thin-clients shape was chosen because a service's internal
language is invisible to its callers.

**In-process embedding is out of scope for v1.** If an app team ever
*requires* embedding the engine in-process inside a Java/Go app (no
network hop), that — and only that — forces a native polyglot core; it is
deferred until a concrete need appears.

## 7. Constraints

- **Language/runtime:** Python, async (asyncio). *(Author's call; owner
  stated Python.)*
- **Jev:** proprietary, hosted API only, early-access waitlist, no
  on-prem, no weights. The framework must tolerate its absence.
- The framework must be **easy to wire into external Kafka / queue /
  worker systems** but must not embed them.
- Open source; plugin contributions must not require core changes.

## 8. Left to the Builder

- Concrete interface signatures and the plugin lifecycle/registration
  mechanism (entry-points layout, versioning of the plugin API).
- The exact content-type abstraction for multimodal, extensible state.
- Batching/concurrency/backpressure implementation details and defaults.
- Reference-plugin implementations for the short-video and ads pipelines
  (ASR, OCR, frame sampling, the Vietnamese proposer, the Jev scorer, the
  LLM-as-judge fallback, policy thresholds, taxonomy store, cache, sinks).
- Test strategy and packaging for `pip`.

## 9. Open Questions for the Owner

Raised by builder-check review (2026-10-19). Two questions only the owner
can answer; answers to be folded in here.

1. **Jev access during the build, and whether image input is real.**
   Do we have working Jev access (or a timeline) while building, or must
   the Jev `Scorer` plugin be built against a mocked schema with the
   LLM-as-judge fallback as the de-facto primary path? And is Jev's image
   input confirmed live? If image input is not real, the visual-fast-path
   (§6.2) is speculative and must be gated behind a capability flag rather
   than assumed as a core cost lever.
   *Answer (owner, 2026-10-19):* **Jev API access is available during the
   build.** The Jev `Scorer` plugin is therefore built and tested against
   the live API, and its image-input support is verified directly against
   the real schema rather than assumed. The LLM-as-judge fallback remains
   mandatory (for open-source contributors without access), but it is no
   longer the de-facto primary path. The visual-fast-path (§6.2) is
   validated against the real API; the capability flag is kept as good
   engineering hygiene, not as a hedge against an unverified feature.

2. **Human-routing budget and whether a second automated tier is wanted.**
   At 50M/day, a strict "hold on doubt" threshold could route tens of
   millions of items to human review — contradicting the "humans
   overloaded" premise. What fraction of traffic can acceptably go to
   humans, and is there a target violation-miss-rate? If the human budget
   is small, the pipeline needs a **second automated arbitration stage**
   (a 6th stage) before falling back to humans; if generous, a single
   threshold suffices.
   *Answer (owner, 2026-10-19):* **Out of scope for the framework.** The
   framework is **budget-agnostic** — it prescribes no human-routing
   budget and no miss-rate SLA. Whoever deploys it tunes their own
   thresholds and decides how much traffic goes to humans. Consequences:
   the Decision Policy stays a **plugin** (§6.1 #4), and the second
   automated arbitration tier is an **optional** plugin stage a deployer
   may insert — not a mandatory 6th stage. The framework ships sane
   defaults but bakes in no budget assumption.

### Calls the author made (builder-check items settled without the owner)

- **Dynamic per-item routing**, not static per-content-type (§6.2).
- **Fire-and-forget, stateless** human-review loop; offline threshold
  tuning (§6.3 #8).
- **Single-node target low-thousands/sec**, and `process_batch` is
  unordered / partial-failure-tolerant / explicit-backpressure (§6.6).
