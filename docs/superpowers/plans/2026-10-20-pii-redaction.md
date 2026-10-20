# PII Redaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a model-agnostic PII-redaction seam — a `Redactor` protocol plus `RedactingScorer`/`RedactingProposer` wrappers and a zero-dependency `RegexRedactor` baseline — that masks content before it crosses to a remote model, leaving the engine's original state untouched.

**Architecture:** A `Redactor` protocol (`async def redact(state) -> State`, with an `accepts` capability set) lives in `labjury.plugins`. Composable wrappers in `labjury.redaction` redact the `State` copy handed to a remote `Scorer`/`Proposer` and delegate everything else, never touching the engine's held `State`; they fail closed on a redactor error and (opt-in, default on) on an uncovered modality. `RegexRedactor` is a baseline covering email/phone/card in text. Zero new dependency; mechanism in core, re-exported top-level — exactly the `reliability` pattern. No engine change.

**Tech Stack:** Python 3.11+, stdlib only (`re`, `typing`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-pii-redaction-design.md`

## Global Constraints

- Core `dependencies = []`; this mechanism is stdlib-only and lives in core (`labjury.redaction` + protocol in `labjury.plugins`). Core never imports `labjury.contrib`.
- Never break the public plugin contract; `Scorer`/`Proposer` signatures unchanged. Wrappers delegate `accepts` from the inner plugin so routing is identical.
- `redact` returns a **new** `State`; a redactor constructs a fresh `Content` for anything it rewrites and may reuse unchanged `Content` by reference. It never mutates its input.
- Fail-closed: a redactor that raises propagates (→ engine `ItemResult(FAILED)`). `strict=True` is the default.
- No new entry-point group, no conformance helper (the `@runtime_checkable` protocol is the check), no `ContextBuilder` wrapper, no image/audio/reversible/injection/secrets work.
- `RegexRedactor` docstring states plainly: baseline only, not a compliance control.
- TDD throughout; commit per task.

## Review Focus

- A redactor that **raises** → item fails, inner plugin never called — pinned in Task 1 (`test_redactor_error_propagates_without_calling_inner`).
- `strict=True` + an uncovered modality present → `UnredactedModalityError`, redactor and inner both never called — pinned in Task 1 (`test_strict_blocks_uncovered_modality`).
- `strict=False` + an uncovered modality → inner called, modality passed through — pinned in Task 1 (`test_non_strict_allows_uncovered_modality`).
- The engine's original `State` is unchanged after a redacting score (copy redacted, not original) — pinned in Task 1 (`test_original_state_unchanged`).
- `RegexRedactor` leaves non-text modalities untouched while masking text — pinned in Task 2 (`test_regex_leaves_non_text_untouched`).

---

### Task 1: `Redactor` protocol + redacting wrappers

**Files:**
- Modify: `src/labjury/plugins.py` (add `Redactor` protocol)
- Create: `src/labjury/redaction.py`
- Test: `tests/test_redaction.py`

**Interfaces:**
- Consumes: `State` (`modalities() -> set[str]`, `get(modality) -> list[Content]`, `add(Content)`, `.flags: set[str]`) from `labjury.state`; `Scorer`/`Proposer` protocols from `labjury.plugins`.
- Produces:
  - `labjury.plugins.Redactor` — `@runtime_checkable` Protocol: attr `accepts: frozenset[str]`; `async def redact(self, state: State) -> State`.
  - `labjury.redaction.UnredactedModalityError(Exception)`.
  - `labjury.redaction.RedactingScorer(inner, redactor, *, strict: bool = True)` — attr `accepts = inner.accepts`; `async def score(self, state, questions) -> list[Answer]`.
  - `labjury.redaction.RedactingProposer(inner, redactor, *, strict: bool = True)` — attr `accepts = inner.accepts`; `async def propose(self, state, context) -> list[Candidate]`.
  - Both guard modalities before redacting: with `strict=True`, if `"*" not in redactor.accepts` and `state.modalities() - redactor.accepts` is non-empty, raise `UnredactedModalityError` before calling redactor or inner.

- [ ] **Step 1: Write the failing tests** in `tests/test_redaction.py`

Fakes: a `_RecordingScorer` (`accepts=frozenset({"*"})`) that stores the `state` it received and returns `[]`; a `_FakeRedactor(accepts=frozenset({"text"}))` whose `redact` returns a new `State` with each `text` payload uppercased and copies `flags`; a `_RaisingRedactor` whose `redact` raises `RuntimeError("boom")`; a `_RecordingProposer`.

```python
async def test_redacting_scorer_passes_redacted_state_to_inner():
    inner = _RecordingScorer()
    s = State(); s.add(Content("text", "hi"))
    out = await RedactingScorer(inner, _FakeRedactor()).score(s, [])
    assert inner.seen.get("text")[0].payload == "HI"
    assert out == []

async def test_original_state_unchanged():
    inner = _RecordingScorer()
    s = State(); s.add(Content("text", "hi"))
    await RedactingScorer(inner, _FakeRedactor()).score(s, [])
    assert s.get("text")[0].payload == "hi"          # original untouched
    assert inner.seen is not s                        # inner saw a copy

async def test_redactor_error_propagates_without_calling_inner():
    inner = _RecordingScorer()
    s = State(); s.add(Content("text", "hi"))
    with pytest.raises(RuntimeError):
        await RedactingScorer(inner, _RaisingRedactor()).score(s, [])
    assert inner.seen is None                         # fail-closed

async def test_strict_blocks_uncovered_modality():
    inner = _RecordingScorer()
    s = State(); s.add(Content("text", "hi")); s.add(Content("image", b"x"))
    with pytest.raises(UnredactedModalityError):
        await RedactingScorer(inner, _FakeRedactor()).score(s, [])   # strict default
    assert inner.seen is None

async def test_non_strict_allows_uncovered_modality():
    inner = _RecordingScorer()
    s = State(); s.add(Content("text", "hi")); s.add(Content("image", b"x"))
    await RedactingScorer(inner, _FakeRedactor(), strict=False).score(s, [])
    assert inner.seen is not None                     # inner was called

async def test_star_redactor_covers_everything_in_strict():
    inner = _RecordingScorer()
    s = State(); s.add(Content("image", b"x"))
    await RedactingScorer(inner, _FakeRedactor(accepts=frozenset({"*"}))).score(s, [])
    assert inner.seen is not None

def test_redacting_scorer_is_a_scorer():
    assert isinstance(RedactingScorer(_RecordingScorer(), _FakeRedactor()), Scorer)

async def test_redacting_proposer_redacts_and_is_a_proposer():
    inner = _RecordingProposer()
    s = State(); s.add(Content("text", "hi"))
    await RedactingProposer(inner, _FakeRedactor()).propose(s, ProposalContext())
    assert inner.seen.get("text")[0].payload == "HI"
    assert isinstance(RedactingProposer(inner, _FakeRedactor()), Proposer)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_redaction.py -v`
Expected: FAIL — `cannot import name 'RedactingScorer'` / `Redactor` not defined.

- [ ] **Step 3: Add the `Redactor` protocol to `src/labjury/plugins.py`**

A `@runtime_checkable` Protocol with `accepts: frozenset[str]` and `async def redact(self, state: State) -> State: ...`, placed beside the other stage protocols.

- [ ] **Step 4: Implement the wrappers in `src/labjury/redaction.py`**

`UnredactedModalityError(Exception)`; a shared `_guard(redactor, state, strict)` helper that raises when strict and a modality is uncovered; `RedactingScorer` and `RedactingProposer` as specified in Interfaces — each stores `inner`, `redactor`, `strict`, sets `self.accepts = inner.accepts`, guards, awaits `redactor.redact(state)`, then delegates to the inner method with the redacted state. Do not catch redactor exceptions.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_redaction.py -v`
Expected: PASS (all of Step 1).

- [ ] **Step 6: Commit**

```bash
git add src/labjury/plugins.py src/labjury/redaction.py tests/test_redaction.py
git commit -m "feat: Redactor seam + RedactingScorer/RedactingProposer wrappers"
```

---

### Task 2: `RegexRedactor` baseline

**Files:**
- Modify: `src/labjury/redaction.py` (add `RegexRedactor`)
- Test: `tests/test_redaction.py` (add cases)

**Interfaces:**
- Consumes: `Redactor` protocol (Task 1), `State`/`Content` from `labjury.state`.
- Produces: `labjury.redaction.RegexRedactor()` — attr `accepts = frozenset({"text"})`; `async def redact(self, state) -> State`. Masks email→`[EMAIL]`, phone→`[PHONE]`, card→`[CARD]` in every `text` payload; returns a new `State` copying `flags`, rewriting `text` `Content` into fresh `Content`, passing non-text `Content` through by reference.

- [ ] **Step 1: Write the failing tests** in `tests/test_redaction.py`

```python
async def test_regex_masks_email_phone_card():
    s = State(); s.add(Content("text", "mail a@b.com call 0912345678 card 4111 1111 1111 1111"))
    out = await RegexRedactor().redact(s)
    masked = out.get("text")[0].payload
    assert "a@b.com" not in masked and "[EMAIL]" in masked
    assert "[PHONE]" in masked and "[CARD]" in masked

async def test_regex_leaves_non_text_untouched():
    s = State(); s.add(Content("image", b"rawbytes"))
    out = await RegexRedactor().redact(s)
    assert out.get("image")[0].payload == b"rawbytes"

async def test_regex_returns_new_state_original_unchanged():
    s = State(); s.add(Content("text", "a@b.com"))
    await RegexRedactor().redact(s)
    assert s.get("text")[0].payload == "a@b.com"

def test_regex_redactor_is_a_redactor():
    assert isinstance(RegexRedactor(), Redactor)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_redaction.py -k regex -v`
Expected: FAIL — `cannot import name 'RegexRedactor'`.

- [ ] **Step 3: Implement `RegexRedactor` in `src/labjury/redaction.py`**

Module-level compiled patterns for email, phone (digit runs/groups of length ≥ 9 with optional `+`/spaces/dashes), and card (four 4-digit groups). `redact` builds a new `State`, copies `flags`, maps each `text` `Content` to a fresh `Content` with the three substitutions applied in order (card before phone, so a card isn't half-eaten by the phone pattern), and appends non-text `Content` unchanged. Docstring: baseline only — misses names/addresses/non-text/obfuscated PII; not a compliance control.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_redaction.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/labjury/redaction.py tests/test_redaction.py
git commit -m "feat: zero-dep RegexRedactor baseline (email/phone/card)"
```

---

### Task 3: Public surface + docs

**Files:**
- Modify: `src/labjury/__init__.py`
- Modify: `tests/test_public_api.py`
- Create: `docs/pii-redaction.md`
- Modify: `README.md`, `README.vi.md`

**Interfaces:**
- Consumes: `Redactor` (Task 1, from `labjury.plugins`); `RedactingScorer`, `RedactingProposer`, `UnredactedModalityError`, `RegexRedactor` (Tasks 1–2, from `labjury.redaction`).
- Produces: all five names importable as `labjury.<name>`.

- [ ] **Step 1: Add the five names to `tests/test_public_api.py`**

Append `"Redactor"`, `"RedactingScorer"`, `"RedactingProposer"`, `"RegexRedactor"`, `"UnredactedModalityError"` to the list in `test_public_surface_importable`.

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_public_api.py::test_public_surface_importable -v`
Expected: FAIL — `missing public export: Redactor`.

- [ ] **Step 3: Re-export the names in `src/labjury/__init__.py`**

Add `Redactor` to the `from labjury.plugins import (...)` block; add a `from labjury.redaction import (RedactingProposer, RedactingScorer, RegexRedactor, UnredactedModalityError)` block; add the five names to `__all__` under a new `# pii redaction` group.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `pytest`
Expected: PASS (all prior tests + redaction + public API).

- [ ] **Step 5: Write `docs/pii-redaction.md` and link it from both READMEs**

`docs/pii-redaction.md`: the trust-boundary framing; the `Redactor` seam; the two wrappers and the composition `lj.ReliableScorer(lj.RedactingScorer(JevScorer(...), lj.RegexRedactor()))`; fail-closed (error + strict); the `RegexRedactor` baseline-not-compliance caveat; the **PII data-flow map** (where personal data travels: into remote scorer/proposer prompts — covered here; into the audit log — already fingerprint-only; into the deployer's own sink/queues/logs — their infrastructure to protect); and the Non-goals. Add a "### PII redaction (opt-in)" section to `README.md` and "### Che dữ liệu cá nhân (tùy chọn)" to `README.vi.md`, each linking `docs/pii-redaction.md`, placed after the reliability section.

- [ ] **Step 6: Commit**

```bash
git add src/labjury/__init__.py tests/test_public_api.py docs/pii-redaction.md README.md README.vi.md
git commit -m "feat: re-export PII redaction surface; docs + data-flow map"
```
