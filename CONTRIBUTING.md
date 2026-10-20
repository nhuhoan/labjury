# Contributing to LabJury

Thanks for considering a contribution. LabJury is a plugin-driven, async decision
engine for labeling and moderation, and it is built to stay small, stable, and
extensible. This guide covers how to set up, the conventions that keep the core
trustworthy, and how to get a change merged.

## Development setup

LabJury targets **Python 3.11+** and has **no runtime dependencies**.

```bash
git clone https://github.com/nhuhoan/labjury
cd labjury
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"        # pytest + pytest-asyncio
pytest                          # the whole suite
```

The test config (`pyproject.toml`) sets `pythonpath = ["src"]` and
`asyncio_mode = "auto"`, so async tests are written as bare `async def test_…`
(no decorator) and the package imports without an editable install when you run
`pytest`. Optional reference backends have extras: `.[redis]`, `.[prometheus]`.

## The rules that keep the core trustworthy

These are not style preferences — they are the guarantees LabJury makes to the
companies that deploy it.

1. **Zero-dependency core.** `[project].dependencies` stays empty. Any code that needs
   a third-party package lives under `labjury.contrib.*` behind an optional extra, and
   **the core never imports `labjury.contrib`** (a subprocess test enforces this).
   Dependency-free mechanisms live in the package proper and are re-exported at top
   level (e.g. `reliability`, `redaction`, `guards`, `secrets`, `rubrics`, `review`,
   `evaluation`).

2. **Test-driven development.** Write the failing test first, watch it fail, then write
   the minimal code to pass. New behavior without a test that failed first will be asked
   to add one. Run the whole suite (`pytest`) before opening a PR, not just your file.

3. **Don't break the public contract.** The public API is exactly what
   `labjury.__all__` exports; the `@runtime_checkable` protocols in `labjury.plugins`
   are the plugin contract. Additive, optional, defaulted fields are fine (minor);
   removing/renaming an export or changing a protocol signature is a major break. See
   [docs/versioning.md](docs/versioning.md).

4. **Bring your own storage.** The engine owns mechanisms, never a fixed database,
   queue, or broker. Durable backends ship as optional reference plugins, never by
   bloating the core.

## Writing a plugin

Implement the relevant `@runtime_checkable` protocol from `labjury.plugins` and prove
it conforms:

```python
from labjury.testing import assert_plugin_conforms
from labjury.plugins import Scorer

assert_plugin_conforms(my_scorer, Scorer)                 # stage plugins
# stateful backends have behavioral suites:
await assert_taxonomy_store_contract(MyTaxonomyStore)
```

Third parties register plugins via the entry-point groups declared in
`pyproject.toml` (`labjury.scorers`, `labjury.proposers`, …); DI-style backends that
need injected clients are used by direct import instead.

## Submitting a change

- Branch off `main`; keep each commit focused and the suite green.
- Match the surrounding code's style; keep files small and single-responsibility.
- User-facing docs are bilingual — update both `README.md` and `README.vi.md` when you
  change the public surface, and add a `docs/<topic>.md` for a new capability.
- Write clear commit messages. When you pair with an AI assistant, keep the
  `Co-Authored-By:` trailer so authorship is honest.
- Open a PR against `main` describing what changed and why, with the test output.

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](./LICENSE) license.
