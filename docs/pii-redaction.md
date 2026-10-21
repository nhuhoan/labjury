# PII redaction — a trust-boundary seam for remote scorers and proposers

Content LabJury classifies — transcripts, OCR text, image payloads — routinely
carries personal data. The highest-risk moment is when that content **leaves
the deployer's trust boundary**: when it is placed into a prompt and sent to a
third-party model (an LLM judge, a remote Jev, a generative proposer). Once it
crosses that line it may be logged, cached, or trained on by a party the
deployer does not control.

LabJury does not try to *be* a PII solution — "what counts as PII" is a policy-,
language-, and law-specific question (GDPR ≠ CCPA ≠ Vietnam's Decree 13/2023),
and every company answers it with their own tools. What LabJury owns is the
**seam**: a standard interception point exactly where content is about to cross
to a remote model, into which you plug *your* redaction policy.

This is the same philosophy as the reliability wrappers — a model-agnostic
standard, not one company's model.

## The seam

```python
@runtime_checkable
class Redactor(Protocol):
    accepts: frozenset[str]            # modalities it covers; {"*"} = any
    async def redact(self, state: State) -> State: ...
```

`redact` returns a **new** `State` and never mutates its input. Plug your own
(Presidio, a cloud DLP API, an in-house NER model, or regex); the
`@runtime_checkable` protocol is the only contract.

## The wrappers

`RedactingScorer` and `RedactingProposer` wrap a remote plugin and redact the
`State` copy it is about to see — the engine's held `State`, the one the policy
and sink see, is **never** touched. So there is nothing to "restore"
afterwards: downstream stages already have the original.

```python
import labjury as lj
from labjury.contrib.jev import JevScorer  # any remote Scorer

scorers = [lj.ReliableScorer(lj.RedactingScorer(JevScorer(...), lj.RegexRedactor()))]
```

Reliability outside, redaction inside: redact once, then the reliable retry
re-sends the already-redacted copy. The wrappers delegate `accepts` from the
inner plugin, so a wrapped plugin routes exactly like the plugin it wraps.

## Fail-closed, two ways

- **On error:** a redactor that raises is *not* caught — the exception
  propagates, and the engine's partial-failure path turns it into an
  `ItemResult(FAILED)`. Nothing reaches the model. A redactor that cannot
  guarantee safety should raise rather than return partially-masked content.
- **On uncovered modality (`strict=True`, the default):** if the `State`
  carries a modality the redactor does not declare in `accepts` (and `"*"` is
  not among them), the wrapper raises `UnredactedModalityError` *before*
  calling the redactor or the model — so a text-only redactor can never
  silently pass an image with a face through to the model. Set `strict=False`
  to allow uncovered modalities through when you understand the exposure.

## The baseline redactor

`RegexRedactor` masks obvious *text* patterns — email → `[EMAIL]`, phone →
`[PHONE]`, card → `[CARD]` — in text payloads and their nested metadata. It is a
**baseline and a test fixture, not a
compliance control**: it misses names, addresses, non-text PII, and obfuscated
forms. Use it to get running on day one, then replace it with a real redactor
behind the same protocol.

## Where PII flows in LabJury (data-flow map)

LabJury covers the remote-model boundary; the rest is your infrastructure to
reason about.

| Path | Who owns it | Status |
|---|---|---|
| Content → remote `Scorer` / `Proposer` prompt | LabJury seam | **Covered** by `RedactingScorer` / `RedactingProposer` |
| Decision → audit log | LabJury | **Safe by default** — the audit trail records content *fingerprints*, never raw content (see [audit-trail.md](audit-trail.md)) |
| Outcome → `Observer` / metrics | LabJury | **Safe by default** — observers see outcomes and latency, not content |
| Verdict / `ItemResult` → your `Sink`, review queue, logs | **You** | Your infrastructure. The engine keeps the original content; where it lands next is your policy to redact, encrypt, or retain |
| Audit / taxonomy backing store (Redis, SQL, …) | **You** | Your storage, your retention and access controls |

## What this is not

Prompt-injection defense (content manipulating the judge's verdict) and secrets
handling (API keys for Jev/LLM) are separate concerns with their own designs.
Image/audio redaction and reversible tokenization are company-provided redactors
behind the same `Redactor` protocol — not shipped here.
