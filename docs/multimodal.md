# Multimodal state — typed inputs, capability routing, and the safety seam

LabJury classifies more than text. A state can hold an image, an audio clip, a
frame sequence, structured JSON, and loose metadata at once. Multimodality is
built into the contract rather than bolted onto it: the `State` is an open
registry of typed content, every stage declares which modalities it consumes,
and the engine routes accordingly. What LabJury owns is the typed container, the
routing, and the trust-boundary seams — **media *processing* (decoding a JPEG,
running OCR, transcribing audio) is your plugins'** job, not the core's.

## The modality registry

Modalities are an open set of strings, never a closed enum. The builtins are
`text`, `json`, `image`, `audio`, `metadata`, and `frame_sequence`; a new one is
a call, not a core edit:

```python
from labjury.state import Content, State, register_content_type

register_content_type("video")          # idempotent; now a valid modality

s = State()
s.add(Content("text", "Please close my card."))
s.add(Content("image", jpeg_bytes, meta={"mime": "image/jpeg"}))
```

`Content.payload` is `Any` — raw bytes, a path, or a URL, whatever your plugins
agree on; put the `mime`/encoding in `meta`. `State` is just a container plus a
mutable `flags` set: `get(modality)`, `has(modality)`, and `modalities()` are
the whole surface. The core never inspects a payload; it moves it.

## Routing by capability (`accepts`)

Every stage plugin declares the modalities it consumes:

```python
class MyImageScorer:
    accepts = frozenset({"text", "image"})     # {"*"} means "any"
    async def score(self, state, questions): ...
```

The engine reads `accepts` and hands a plugin only the work it can do — a
text-only scorer never sees an image, and a scorer that declares `image` does.
`ContextBuilder`s `produce` modalities too, so a pipeline can turn a raw item
into `image` content a downstream scorer then consumes. The reliability,
redaction, and guard wrappers all **delegate `accepts` from the plugin they
wrap**, so wrapping never changes how a plugin routes.

This is why adding a modality is not a core change: a new input type is a new
registered string plus the plugins that declare they accept it.

## The safety seam: no modality crosses to a remote model uncovered

Multimodality widens what leaves your trust boundary — an image can carry a face
or a document with a name on it, and once it reaches a third-party model it may
be logged, cached, or trained on. LabJury makes that widening **impossible to do
silently**.

`RedactingScorer` / `RedactingProposer` run in `strict=True` mode by default: if
the state carries a modality the redactor does not declare in `accepts` (and
`"*"` is not among them), the wrapper raises `UnredactedModalityError`
*before* the redactor or the model is called. So turning on image input with a
text-only redactor does not quietly start shipping unredacted images — it fails
closed, and you either plug a redactor that covers `image` or set `strict=False`
once you understand the exposure. The strict-mode coverage check **is** the
multimodal safety contract. See [pii-redaction.md](pii-redaction.md).

Guards see the whole state, not just its text. The baseline
`HeuristicInjectionGuard` only scans `text`, but a `Guard` you plug in can
inspect `state.get("image")` for embedded-instruction attacks on the same
inspect-and-reject seam. See [prompt-injection.md](prompt-injection.md).

## A multimodal scorer (illustrative)

A scorer that sends images declares it, serializes each `Content("image", …)`
into its model's wire format, and otherwise looks like any other scorer:

```python
class ExampleVisionScorer:
    accepts = frozenset({"text", "image"})

    def __init__(self, transport):
        self._transport = transport          # injected; owns HTTP + auth

    async def score(self, state, questions):
        payload = {
            "text": [c.payload for c in state.get("text")],
            "images": [encode(c.payload, c.meta) for c in state.get("image")],
            "questions": [...],
        }
        resp = await self._transport(payload)
        return [...]
```

How an image goes on the wire — base64, a signed URL, a reference id — is the
**model's** contract, not LabJury's, so a concrete vision adapter belongs in an
`examples/` reference (or a separate `pip` package), never in the model-agnostic
core.

## What LabJury owns, and what you own

| Concern | Owner |
|---|---|
| Typed multimodal container (`State` / `Content`) and the open modality registry | **LabJury** |
| Routing work to the stages that `accept` each modality | **LabJury** |
| Fail-closed guarantee that no modality reaches a remote model without redaction coverage | **LabJury** (strict mode) |
| The inspect-and-reject guard seam over the whole state | **LabJury** |
| Decoding / OCR / transcription / any media processing | **You** (a `ContextBuilder` / `Proposer` plugin) |
| Per-model image serialization (base64 / URL / …) | **You** (the model's adapter) |
| Image / audio redactors and non-text guards | **You** (behind the same protocols) |

## See also

- [pii-redaction.md](pii-redaction.md) — the redaction seam and strict-mode coverage.
- [prompt-injection.md](prompt-injection.md) — the guard seam.
- [reliability.md](reliability.md) — wrapping a remote scorer for timeouts, retries, failover.
