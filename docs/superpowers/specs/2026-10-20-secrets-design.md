# Secrets — a leak-resistant credential holder and a no-store guarantee

**Status:** design (CTO-decided; owner delegated design authority) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-20
**Tier / step:** Enterprise readiness Tier 1, step 5 (security) — the **secrets** slice, last of the three (after PII redaction and prompt-injection).

## Intent and the why

LabJury's plugins talk to remote models (Jev, an LLM judge, ASR) with API keys.
Two failure modes matter: a framework that **stores** credentials (wrong — every
company has its own secret manager; same "no fixed storage" rule as everywhere
else), and a framework that **leaks** them — a key landing in a log line, a
traceback, or an audit record.

LabJury already avoids *storing* secrets: plugins receive already-configured
clients by dependency injection; the core never asks for a credential. The real
exposure is *leakage*, and there is one concrete LabJury-owned path:
`ProvenanceRef.params` on an `AuditEvent` records "how a plugin was configured"
and is serialized verbatim into whatever store the deployer plugs in. A
deployer who drops a raw key into those params leaks it into their audit store.

So this slice ships two things, matching the framework's philosophy — a
mechanism, not a policy:

1. A **leak-resistant `Secret` holder** so a credential kept in config, passed
   around, or accidentally placed in provenance params does **not** reveal
   itself in `repr()`, `str()`, f-strings, or `json.dumps` (it fails loud
   instead of serializing). The deployer calls `.reveal()` only at the point of
   use.
2. A documented **no-store guarantee + guidance**: LabJury core never asks for,
   stores, or logs credentials; plugins get configured clients; the audit trail
   is fingerprint-only; and any sensitive config value should be wrapped in
   `Secret` so it can't leak through the one path that records config.

## Goals

- `labjury.secrets.Secret(value: str)` — zero-dependency, in core, top-level re-exported:
  - `reveal() -> str` returns the underlying value (the only way to read it).
  - `__repr__` → `Secret('***')`; `__str__` → `'***'`. The value never appears in either, nor in an f-string via `{x}` or `{x!r}`.
  - `__eq__` compares two `Secret`s by underlying value; comparison with a non-`Secret` is `NotImplemented` (so `Secret("k") == "k"` is `False`, discouraging raw comparison). `__hash__` by underlying value so it is usable in sets/dict keys.
  - **Not JSON-serializable**: `json.dumps(Secret(...))` raises `TypeError` — a leak into a store fails loud rather than silently writing the value.
- Docs: `docs/secrets.md` (the no-store guarantee, the `ProvenanceRef.params` caveat, `Secret` usage) + bilingual README pointers.

## Non-goals / anti-goals

- **No secret store, no secret manager integration, no env-var loading, no rotation.** That is the deployer's infrastructure (Vault, AWS/GCP secret managers, k8s secrets). LabJury neither reads nor holds the source of truth.
- **No automatic scrubbing** of arbitrary log output or exception messages. `Secret` is opt-in at the value level; LabJury cannot rewrite a third-party plugin's exception text.
- **No encryption at rest / in memory.** `Secret` is leak-resistance against accidental disclosure (repr/str/serialize), not a cryptographic container; `reveal()` returns the plaintext.
- **No change to `AuditEvent` / `ProvenanceRef`.** They already serialize `params` verbatim; the fix is the `Secret` value wrapper plus guidance, not a schema change.

## Constraints (inherited)

- Core `dependencies = []`; stdlib-only; mechanism in `labjury.secrets`; core never imports `labjury.contrib`.
- No public plugin contract changes.
- Python 3.11+. TDD throughout; each task independently testable; frequent commits.

## The parts of the how, as decided

### `Secret` (`labjury/secrets.py`, zero-dep)

```python
class Secret:
    __slots__ = ("_value",)
    def __init__(self, value: str) -> None: ...
    def reveal(self) -> str: ...
    def __repr__(self) -> str:  # "Secret('***')"
    def __str__(self) -> str:   # "***"
    def __eq__(self, other) -> bool:   # by value, only against another Secret
    def __hash__(self) -> int:         # by value
```

`__slots__` keeps the value off a mutable `__dict__`. There is no attribute that
exposes the value — only `reveal()`. Not JSON-serializable falls out for free (a
plain object with no `__dict__` and no serializer); a test pins it so it cannot
regress.

### Public surface

Re-exported from `labjury`: `Secret`. Added to `__all__` under a `# secrets`
group and to `test_public_api.py`'s importable list.

## What's left to the builder

- The exact mask string (`'***'`) is fixed above; the repr/str spelling is the builder's to match the tests.
- Test fixture values (any non-empty secret-looking string).

## Review focus (inputs the tests must pin)

- The value never appears in `repr`, `str`, or an f-string (`{x}` and `{x!r}`).
- `reveal()` returns the exact original value.
- `json.dumps(Secret(...))` raises `TypeError` (fails loud, no silent leak).
- Two `Secret`s with the same value are equal and hash equal; `Secret("k") == "k"` is `False`.
