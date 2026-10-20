<div align="center">

# ⚖️ LabJury

**A plugin-driven, async decision engine for labeling and moderation at scale.**

*Proposers plead · a scorer judges · a verdict is rendered.*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE)
[![Status](https://img.shields.io/badge/status-core-orange)]()

English · [Tiếng Việt](./README.vi.md)

</div>

---

## What is LabJury?

Classifying content at scale — tagging videos, moderating ads, routing
tickets — is drowning teams in two ways at once: humans can't keep up with the
volume, and the AI that's supposed to help keeps **missing violations**,
**skipping anything it has no label for**, and **misreading nuance, slang, and
implied meaning**.

LabJury is a framework for doing that classification well, cheaply, and
safely. Its central idea is a division of labor:

> **A generative model *proposes* candidate labels. A decision-only model
> *judges* them. A policy renders the verdict.**

The expensive part (a large language model *generating* candidate labels) runs
sparingly. The high-volume part (*scoring* those candidates) runs on a fast,
cheap, decision-only model — such as [Jev](https://typesafe.ai) from TypeSafe
AI, which returns typed answers (`Choice` / `Score` / `Noul`) with a
confidence value instead of prose. That is what makes quality, safety, and low
cost reconcilable at tens of millions of items per day.

### The name

**LabJury** = **LAB**(EL) + **JURY**. The architecture *is* a jury: many
voices present evidence — a transcript, the text in an image, hashtags,
proposed labels — a judge weighs them, and a verdict with a confidence is
returned. Read as a backronym it spells out what it does:

> **L**abeling **A**nd **B**atch **J**udgment **U**nder **R**anked
> **Y**ardsticks.

---

## Why it's built this way

| Principle | What it means in practice |
|---|---|
| **No hard dependency on any one model** | Jev is just one `Scorer`. A built-in `LLMJudgeScorer` lets the whole pipeline run with any chat LLM — so you (and open-source contributors without Jev access) are never blocked. |
| **Open-world taxonomy** | Content that matches no known label is surfaced as a *proposed new label* for human review — **never silently dropped**. This is how the label set grows instead of going stale. |
| **Recall-biased safety** | A possible policy violation is **held for review unless the scorer is confidently clean**. "When in doubt, hold it" — never "when unsure, let it through." |
| **Multimodal, extensible state** | `text` · `json` · `image` · `audio` · `metadata` · `frame_sequence`, and any type you register. The core never knows a *closed* set of modalities. |
| **Fast-processing mechanisms, not scale** | Async end-to-end, batching, bounded concurrency, explicit backpressure, caching. Queues, storage, autoscaling, and the road to 50M/day are **your** infrastructure — built *around* LabJury, not inside it. |
| **Plugins via entry-points** | Ship a `pip` package that registers under `labjury.<kind>`; the core never changes. |

---

## The pipeline

```
          ┌──────────────┐   ┌───────────┐   ┌────────┐   ┌───────────────┐   ┌──────┐
 item ──▶ │ ContextBuilder│──▶│ Proposer  │──▶│ Scorer │──▶│ DecisionPolicy│──▶│ Sink │──▶ verdict
          └──────────────┘   └───────────┘   └────────┘   └───────────────┘   └──────┘
             enrich state      propose         judge          accept /          route to
           (ASR, OCR, …)       candidate       (Jev or        block / hold       DB / review /
                               labels          LLM-judge)                        new-label
                                   ▲
                                   └── skipped on the visual fast-path
```

**Routing is dynamic, per item.** A purely visual item (say, an image that
only needs a nudity/logo check) skips the expensive Proposer and goes straight
to an image-capable scorer. Only semantically hard items (implied meaning,
slang) take the long route.

---

## Quick start (runs without Jev)

```python
import asyncio
import labjury as lj

async def chat(prompt: str) -> str:
    # Plug any async chat LLM here; it must return JSON {"value": ..., "confidence": ...}
    return '{"value": "food", "confidence": 0.95}'

class TextBuilder:
    accepts = frozenset({"*"}); produces = frozenset({"text"})
    async def build(self, item, state):
        state.add(lj.Content("text", item.raw["text"])); return state

class FoodProposer:
    accepts = frozenset({"*"})
    async def propose(self, state, context):   # context.known_labels = official vocabulary
        return [lj.Candidate("food", "tag", lj.ChoiceQuestion("food_q", "food?", ["food"]))]

engine = lj.Engine(
    context_builders=[TextBuilder()],
    proposers=[FoodProposer()],
    scorers=[lj.LLMJudgeScorer(chat=chat)],   # swap for a Jev scorer in production
    policy=lj.RecallBiasedPolicy(),
    sink=lj.CollectingSink(),
    cache=lj.InMemoryCache(),
    taxonomy=lj.InMemoryTaxonomyStore(),
    observer=lj.InMemoryObserver(),
)

result = asyncio.run(engine.process(lj.Item("item-1", {"text": "món ăn ngon"})))
print(result.status, result.verdict)
```

---

## The `process_batch` contract

An external worker (behind your own Kafka/queue) drives the engine. Its batch
API is a **frozen contract** — integrators build their scaling on it:

- **Unordered** — each result carries its item's `correlation_id`, not its list position.
- **Partial-failure-tolerant** — one bad item yields a `FAILED` result; its siblings are still decided.
- **Explicit backpressure** — items beyond `max_concurrency` in a call return `RETRY_LATER`, so the caller re-enqueues rather than the engine blocking.

---

## Extending LabJury

Every stage is a plugin discovered via entry-points. In your package's
`pyproject.toml`:

```toml
[project.entry-points."labjury.scorers"]
my_jev = "my_package.scorers:JevScorer"
```

Then `labjury.load_entry_points()` makes it available. Plugin kinds:
`context_builders`, `proposers`, `scorers`, `policies`, `sinks`,
`taxonomies`, `caches`.

### Durable & custom taxonomy backends

The taxonomy's vocabulary should outlive a restart. A Redis reference backend
ships built-in:

```bash
pip install labjury[redis]
```

```python
from labjury.contrib.redis_taxonomy import RedisTaxonomyStore
engine = lj.Engine(..., taxonomy=RedisTaxonomyStore(async_redis_client))
```

Redis is just one option — back the taxonomy with your own system (Postgres,
DynamoDB, an in-house store) by implementing the `TaxonomyStore` protocol, and
verify it with the shipped conformance suite
(`labjury.assert_taxonomy_store_contract`). See
[docs/taxonomy-backends.md](docs/taxonomy-backends.md).

### Audit trail (opt-in, storage-agnostic)

Record an immutable `AuditEvent` per decision and replay it later:
`lj.Engine(..., audit=lj.InMemoryAuditLog())`. LabJury ships **no database** —
bring your own store (Kafka/S3/SIEM/SQL) via the append-only `AuditLog` protocol
and the `AuditEvent.to_dict`/`from_dict` seam, verified with
`labjury.assert_audit_log_contract`. A durable SQLite reference backend ships
built-in (`labjury.contrib.sqlite_audit.SqliteAuditLog`, no extra needed). See
[docs/audit-trail.md](docs/audit-trail.md).

---

## Roadmap

- **Core** — this package. ✅
- **Reference plugins** — live Jev scorer, a Vietnamese-strong proposer, ASR/OCR/frame-sampling context builders, a persistent (Redis) taxonomy & cache, and the short-video + ads reference pipelines.
- **Service + polyglot clients** — a stateless gRPC service (with optional REST/JSON) wrapping the engine, plus thin generated clients for **Java, Go, PHP, Python**, so application teams consume LabJury without touching Python.

---

## License

[Apache-2.0](./LICENSE)
