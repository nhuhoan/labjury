# PII Redaction — a trust-boundary seam for remote scorers and proposers

**Status:** design, awaiting approval
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness Tier 1, step 5 (security) — the **PII**
slice. Prompt-injection and secrets are the sibling slices, deliberately out
of scope here (see Non-goals).

## Intent and the why

LabJury classifies real content — transcripts, OCR text, image payloads —
and that content routinely carries personal data: names, phone numbers,
emails, card numbers, faces. The highest-risk moment is when that content
**leaves the deployer's trust boundary**: when it is placed into a prompt and
sent to a third-party model (an LLM judge, a remote Jev, a generative
proposer). Once it crosses that line it may be logged, cached, or used for
training by a party the deployer does not control.

LabJury must not pretend to *be* a PII solution. "What counts as PII" is a
policy-, language-, and law-specific question (GDPR ≠ CCPA ≠ Vietnam's Decree
13/2023), and every company answers it differently with their own tools. A
framework that hard-codes that answer is wrong for most of its users and
quietly assumes their legal liability.

What the framework *can* own — and what this step delivers — is:

1. **A standard interception point** (a seam) exactly where content is about
   to cross to a remote model, into which a company plugs *their* redaction
   policy (Presidio, cloud DLP, an in-house NER model, or regex).
2. **Safe-by-construction defaults** so the framework's own paths do not leak
   raw PII, and a documented map of where PII flows so a security team can
   reason about the parts LabJury does not own.
3. **A zero-dependency baseline redactor** so OSS users get something that
   runs on day one and the test suite has a concrete implementation —
   explicitly labelled *not compliance-grade*.

This mirrors the reliability step's philosophy exactly: LabJury ships a
model-agnostic **standard**, not one company's model.

## Goals

- Define a `Redactor` protocol: `async def redact(self, state: State) ->
  State`, plus an `accepts: frozenset[str]` capability declaration (which
  modalities it covers), consistent with every other plugin.
- Ship `RedactingScorer` and `RedactingProposer` — composable wrappers that
  redact the `State` a remote plugin is about to see, leaving the engine's
  original `State` untouched. They compose with the reliability wrappers:
  `ReliableScorer(RedactingScorer(JevScorer(...), redactor))`.
- Ship `RegexRedactor` — a zero-dependency baseline covering obvious,
  high-value *text* patterns (email, phone, credit-card), replacing each
  match with a stable placeholder (`[EMAIL]`, `[PHONE]`, `[CARD]`).
- **Fail-closed by construction:** a redactor that raises (cannot guarantee
  safety) propagates the exception; the engine's existing partial-failure
  path turns it into `ItemResult(FAILED)` — nothing reaches the model. No
  engine change.
- **Fail-closed on uncovered modality (opt-in default):** a `strict=True`
  wrapper option (default on) raises if the `State` contains a modality the
  redactor does not declare in `accepts`, so a text-only redactor cannot
  silently pass an image with a face through to the model.
- Zero new dependency; the mechanism lives in core (`labjury.redaction`) and
  the protocol in `labjury.plugins`, both top-level re-exported — same rule
  as `reliability` (contrib carries deps; dependency-free mechanisms live in
  the package proper).
- Documentation: a `docs/pii-redaction.md` plus a short **PII data-flow map**
  (where personal data travels through LabJury, what is already safe, and
  what is the deployer's own infrastructure to protect), and bilingual README
  pointers.

## Non-goals / anti-goals

- **No built-in PII detector/classifier.** The baseline regex is a
  convenience and a test fixture, never a compliance control. We will not grow
  it into a general detector.
- **No image/audio redaction implementation.** The seam accepts any modality;
  the baseline covers text only. Face-blurring / audio-scrubbing are
  company-provided redactors behind the same protocol.
- **No prompt-injection defense and no secrets handling here.** They are the
  other two slices of the security step and get their own design, one at a
  time.
- **No reversible tokenization / restore.** Because the wrapper redacts only
  the *copy* handed to the model and the engine keeps the original, downstream
  stages (policy, sink, human review) already see the untouched content — so
  there is nothing to "restore". A company that needs vault-backed reversible
  tokens builds it behind the `Redactor` protocol.
- **No `ContextBuilder` redaction wrapper.** A context builder *creates*
  content (ASR/OCR); you cannot redact the audio you are about to transcribe
  without defeating the transcription. PII egress is governed where content is
  *consumed* by a remote judge — the scorer and proposer. Builders are
  excluded deliberately.
- **No `/metrics`-style new infrastructure, no new entry-point group.**
  Redactors are injected by direct import into the wrapper, like the inner
  plugins the reliability wrappers wrap.

## Constraints (inherited, verbatim where they bind)

- Never break the public plugin contract; `Scorer` / `Proposer` signatures are
  unchanged.
- Core never imports `labjury.contrib`; this mechanism is zero-dep and lives in
  core.
- No database, no fixed storage dependency.
- Python 3.11+, `dependencies = []` in core.
- TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### The seam

```python
# labjury/plugins.py
@runtime_checkable
class Redactor(Protocol):
    accepts: frozenset[str]           # modalities it can redact; {"*"} = any
    async def redact(self, state: State) -> State: ...
```

`redact` returns a **new** `State` (it never mutates its input), so the
engine's held `State` — the one policy and sink see — is never altered. A
redactor must construct a **fresh `Content`** for anything it rewrites
(`Content` is a mutable dataclass; rewriting a payload in place would corrupt
the shared original); unchanged `Content` may be reused by reference since
nothing downstream mutates it. No separate conformance helper ships: the
`@runtime_checkable` protocol is the structural check (same ruling as the
telemetry `Observer`).

### The wrappers (`labjury/redaction.py`, zero-dep)

```python
class RedactingScorer:
    def __init__(self, inner, redactor, *, strict: bool = True): ...
    #   self.accepts = inner.accepts   (routes exactly like the inner plugin)
    async def score(self, state, questions):
        self._guard_modalities(state)          # strict-mode coverage check
        redacted = await self._redactor.redact(state)
        return await self._inner.score(redacted, questions)

class RedactingProposer:   # same shape, delegates propose(state, context)
    ...
```

- The wrapper does **not** catch the redactor's exceptions → fail-closed on
  error.
- `strict=True`: if `state.modalities()` contains anything not covered by
  `redactor.accepts` (and `"*"` is not present), raise `UnredactedModalityError`
  (an `Exception` subclass, so it flows through the engine's partial-failure
  path like any other give-up) *before* calling the redactor or the model →
  fail-closed on coverage.
- `accepts` is delegated from the inner plugin so a wrapped plugin routes
  identically (same contract the reliability wrappers honour).

### The baseline (`RegexRedactor`, zero-dep)

- `accepts = frozenset({"text"})`.
- Compiled patterns for email, international/US-style phone numbers, and
  credit-card-shaped digit groups; each match → `[EMAIL]` / `[PHONE]` /
  `[CARD]`.
- Builds a new `State`: copies `flags`, rewrites each `text` `Content.payload`
  through the patterns, passes non-text `Content` through unchanged.
- Docstring states plainly: baseline only — misses names, addresses,
  non-text PII, and obfuscated forms; not a compliance control.

### Public surface

Re-exported from `labjury`: `Redactor`, `RedactingScorer`, `RedactingProposer`,
`RegexRedactor`, `UnredactedModalityError`. Added to `__all__` under a
`# pii redaction` group and to `test_public_api.py`'s importable list.

### Composition the deployer writes

```python
scorers=[lj.ReliableScorer(lj.RedactingScorer(JevScorer(...), lj.RegexRedactor()))]
```

Reliability outside, redaction inside: on a transient model failure the
reliable retry re-runs redaction and re-sends. A *deterministic* redaction
failure (a raise, or a strict-mode uncovered modality) is retried the
configured number of times and then surfaces as `FAILED` — correct, mildly
wasteful, and acceptable; a deployer who wants no retry on it sets
`retries=0` on the reliability wrapper.

## What's left to the builder

- Exact regex patterns and placeholder spelling (the design fixes the three
  categories and the `[EMAIL]`/`[PHONE]`/`[CARD]` style; the builder writes
  patterns that pass the table of positive/negative cases the plan will name).
- Whether `State` gains a small `copy()` helper or the redactor rebuilds a
  `State` inline — builder's call; both keep the original untouched.
- Test fixture shapes (a `FakeRedactor`, a raising redactor, a State with a
  non-text modality for the strict-mode test).

## Review focus (inputs the tests must pin)

- A redactor that **raises** → item `FAILED`, inner plugin never called.
- `strict=True` with an uncovered modality present → `UnredactedModalityError`,
  redactor and inner plugin never called.
- `strict=False` with an uncovered modality → inner plugin called; uncovered
  modality passed through (documented, deliberate).
- The engine's original `State` is **unchanged** after a redacting score (the
  copy was redacted, not the original).
- `RegexRedactor` leaves non-text modalities untouched and redacts every
  listed text pattern.
- A `RedactingScorer` still satisfies the `Scorer` protocol
  (`isinstance(..., Scorer)` via `@runtime_checkable`); same for proposer.
