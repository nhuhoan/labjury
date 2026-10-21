# Human-in-the-loop review

When a policy returns `Action.REVIEW`, the machine is not confident enough and a
human should adjudicate. LabJury owns the **hand-off contract** for that — portable
task and resolution objects, and a queue seam — but not the queue, the workflow, or
the people. The contract is **stateless and fire-and-forget**: LabJury packages a
review task, hands it off, and forgets it. Running the review queue, assigning
reviewers, tracking SLAs, and feeding decisions back is the deployer's
orchestration.

## The round-trip the deployer wires

```
engine.process(item) -> ItemResult(status=REVIEW)
          │
          ▼  (deployer sees a REVIEW result; reads its audit event)
review_task_from_event(event, content_ref="items/post-42") -> ReviewTask
          │
          ▼  queue.enqueue(task)        # fire-and-forget
   [ the deployer's review backend: ticketing tool, labeling UI, SQS, DB … ]
          │
          ▼  a human decides
ReviewResolution(correlation_id, action, labels, reviewer, note)
          │
          ▼  resolution.to_verdict() -> Verdict    # the final decision
```

LabJury supplies every box except the backend and the human. The engine is **not**
involved in any of it — it does not hold a queue and does not enqueue on `REVIEW`.
That is deliberate: it keeps the framework autonomous of your message broker and
review workflow.

## `ReviewTask` — the hand-off package

```python
import labjury as lj

task = lj.review_task_from_event(event, content_ref="items/post-42")
task.correlation_id      # ties back to the item
task.content_ref         # key used by your review system to fetch the original content
task.candidates          # the proposed labels + their questions
task.answers             # what the scorer answered
task.tentative_verdict   # what the machine tentatively decided (REVIEW)
task.tenant              # who it was for
task.to_dict()           # JSON-serializable — it crosses to your review system
```

The audit event contains the decision context, not the original content.
`content_ref` is a required key or URI in your own storage; the review system
uses it (with `tenant` where applicable) to load the content. Do not put raw
content in the audit log. You can also build a `ReviewTask` directly.

## `ReviewQueue` — the fire-and-forget seam

```python
class ReviewQueue(Protocol):
    async def enqueue(self, task: ReviewTask) -> None   # hand off and return
```

LabJury's side of the contract is a single write. It never pulls, acks, or waits —
your backend and your consumers own that. `InMemoryReviewQueue` is the zero-dep
reference (`enqueue`, plus `pending()` / `drain()` for tests and local runs); a
durable backend (SQS, a DB table, Pub/Sub) implements the one `enqueue`.

## `ReviewResolution` — the human decision coming back

```python
resolution = lj.ReviewResolution("post-42", "block", ["nsfw"], reviewer="alice",
                                 note="clear violation")
verdict = resolution.to_verdict()    # Verdict(action=BLOCK, labels=["nsfw"], …)
```

`to_verdict()` turns the human's choice into a final `Verdict` (scores empty — a
human produces no model scores; an unknown action string raises). The deployer wraps
it in an `ItemResult`, emits it to their sink, or records it — as they see fit.

## Auditing the override

The hand-off out (`review_task_from_event`) is a one-way exit from the audit
trail; `override_event` is the way back in. It records "machine said REVIEW →
reviewer *alice* decided BLOCK at *T*" as a new immutable `AuditEvent`:

```python
event = ...                              # the decision's original AuditEvent
resolution = lj.ReviewResolution("post-42", "block", ["nsfw"], reviewer="alice")

record = lj.override_event(event, resolution)
await audit_log.record(record)           # your AuditLog, your timing
```

The produced event:

- **links** to the original by `correlation_id` (and raises `ValueError` if the
  resolution's `correlation_id` doesn't match — recording an override against the
  wrong decision);
- **carries forward the inputs the human saw** (`input_fingerprint`, `modalities`,
  `candidates`, `answers`, `known_labels`, `tenant`);
- **records the human's verdict** (`resolution.to_verdict()`, scores empty);
- **attributes it to the reviewer alone** — `provenance["reviewer"]` holds the
  reviewer name plus the note and `decided_at`; the machine's scorer/policy
  provenance stays on the original event, so the two events (same
  `correlation_id`) together tell the full story;
- is a **distinct event** (fresh `event_id`/`occurred_at`).

It is a pure function — the deployer still owns *when* and *how* the write
happens (fire-and-forget), consistent with the rest of this contract.

## Non-goals

- **No engine auto-enqueue** — wiring REVIEW results to the queue is deployer code.
- **No consumer loop, ack/nack, visibility timeout, assignment, SLA, or escalation** —
  that is your review workflow.
- **No queue storage** — `InMemoryReviewQueue` is a reference, not a broker; bring
  your own.
