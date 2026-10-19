# LabJury

A plugin-driven, async decision engine for labeling and moderation.

**Proposers plead, a scorer judges, a verdict is rendered.** A generative
step *proposes* candidate labels; a scorer (e.g. [Jev](https://typesafe.ai),
or the built-in LLM-as-judge fallback) *scores and confirms* them; a
recall-biased policy turns scores + confidence into a verdict. The expensive
generative work runs sparingly; the high-volume scoring runs on a cheap,
decision-only model.

- **No hard dependency on Jev.** `LLMJudgeScorer` lets the whole pipeline run
  with any chat LLM, so contributors without Jev access can still use it.
- **Open-world taxonomy.** Content matching no known label is surfaced as a
  *proposed new label* for review — never silently dropped.
- **Recall-biased safety.** A possible policy violation is held for review
  unless the scorer is confidently clean.
- **Multimodal, extensible state.** text / json / image / audio / metadata /
  frame-sequence, and any type you register — never a closed enum.
- **Fast-processing mechanisms, not scale.** Async, batching, bounded
  concurrency, explicit backpressure, caching. Queues, storage, and scaling
  live outside the framework.
- **Plugins via entry-points.** Ship a `pip` package registering under
  `labjury.<kind>`; no core change required.

## Pipeline

```
item -> ContextBuilder(s) -> [Proposer] -> Scorer -> DecisionPolicy -> Sink
                               (skipped on the visual fast-path)
```

Routing is dynamic per item: a purely visual item can skip the Proposer and
go straight to an image-capable scorer.

## Quick start (runs without Jev)

```python
import asyncio
import labjury as lj

async def chat(prompt: str) -> str:
    # plug any async chat LLM here
    return '{"value": "food", "confidence": 0.95}'

class TextBuilder:
    accepts = frozenset({"*"}); produces = frozenset({"text"})
    async def build(self, item, state):
        state.add(lj.Content("text", item.raw["text"])); return state

class FoodProposer:
    accepts = frozenset({"*"})
    async def propose(self, state):
        return [lj.Candidate("food", "tag", lj.ChoiceQuestion("food_q", "food?", ["food"]))]

eng = lj.Engine(
    context_builders=[TextBuilder()],
    proposers=[FoodProposer()],
    scorers=[lj.LLMJudgeScorer(chat=chat)],
    policy=lj.RecallBiasedPolicy(),
    sink=lj.CollectingSink(),
    cache=lj.InMemoryCache(),
    taxonomy=lj.InMemoryTaxonomyStore(),
    observer=lj.InMemoryObserver(),
)
result = asyncio.run(eng.process(lj.Item("i1", {"text": "món ăn ngon"})))
print(result.status, result.verdict)
```

## `process_batch` contract

Results are **unordered** (each carries its item's correlation id),
**partial-failure-tolerant** (one bad item yields a `FAILED` result, siblings
unaffected), and backpressure is **explicit** (items beyond `max_concurrency`
in a call return `RETRY_LATER` so the caller re-enqueues).

## Status

Core (this package). Reference plugins (live Jev, Vietnamese proposer,
ASR/OCR, short-video & ads pipelines) and a gRPC service with thin Java / Go
/ PHP clients are planned follow-ups.

## License

Apache-2.0
