# Governance docs — contributing, security, conduct

**Status:** design (CTO-decided; owner delegated, "ok làm luôn đi" 2026-10-21) — building proceeds
**Author:** nhuhoan (with Claude Opus 4.8)
**Date:** 2026-10-21
**Tier / step:** Enterprise readiness **Tier 3** (ecosystem), **item 3 of 3** — governance docs. Docs-only; closes the ecosystem-documentation piece. (The gRPC service, Tier 3 item 1, is deferred as a separate consequential subsystem pending owner sign-off.)

## Intent and the why

LabJury is a public OSS framework. Tier 1–2 gave it the capabilities and Tier-3 item 2
gave it a versioned, conformance-tested contract. What a public project still lacks is
the **community contract**: how to contribute, how to report a vulnerability, and the
behavioral norms. These are the standard files maintainers and scanners (and GitHub's
community-profile checks) look for. They are prose, so no code or tests — only accuracy
against how the project actually works.

## Goals

- **`CONTRIBUTING.md`** — the real dev workflow: Python 3.11+, `pip install -e
  .[test]` or the `pythonpath=src` pytest setup; run `pytest` (auto asyncio mode);
  the **zero-dep-core rule** (core `dependencies = []`; dependency-carrying plugins go
  under `labjury.contrib`; core never imports contrib); **TDD discipline** (a failing
  test first); the **plugin convention** (implement a `@runtime_checkable` protocol;
  prove it with `assert_plugin_conforms` / the `assert_*_store_contract` suites); the
  **public-surface/SemVer rule** (only `__all__` is public; link `docs/versioning.md`);
  bilingual docs (`README.md` + `README.vi.md`); and the commit convention
  (`Co-Authored-By` trailer when pairing with an assistant).
- **`SECURITY.md`** — how to report a vulnerability (GitHub private security advisories
  on the repo as the primary channel; no public issue for undisclosed vulns); supported
  versions (latest `main` while pre-1.0); and an **honest security-posture statement**:
  the built-in redaction (`RegexRedactor`), injection guard (`HeuristicInjectionGuard`),
  and `Secret` are **mechanisms/baselines, not compliance controls or cryptography** —
  deployers plug their own detectors/secret managers (cross-links the security docs).
- **`CODE_OF_CONDUCT.md`** — the Contributor Covenant v2.1, with the report contact set
  to the project's GitHub security/advisory channel (no personal email hard-coded).
- **README wiring** — a "## Contributing & governance" section (bilingual) linking the
  three files and `docs/versioning.md`, placed before the License section.

## Non-goals / anti-goals

- **No gRPC service** — Tier 3 item 1, deferred (consequential, dependency-heavy,
  separate sign-off).
- **No CI config, no issue/PR templates, no release automation** — can come later; this
  slice is the three core governance documents + README wiring.
- **No new code, no dependency, no public-surface change.** Prose only.
- **No personal email in public files** — use the repo's GitHub advisory channel.

## Constraints (inherited)

- Accuracy over aspiration: every workflow statement must match how the repo actually
  builds and tests today (zero-dep core, `pythonpath=src`, pytest-asyncio auto, extras
  `test`/`redis`/`prometheus`, Apache-2.0).
- Bilingual pointer parity (`README.md` + `README.vi.md`).
- The full suite must still pass after the change (docs don't touch code, but verify).

## What's left to the builder

- Exact Contributor Covenant wording is the canonical v2.1 text (verbatim).
- The precise enforcement/report line in the CoC points to the GitHub advisory channel.

## Review focus

- CONTRIBUTING matches the real build/test setup and the zero-dep/contrib + TDD +
  SemVer conventions (no invented steps).
- SECURITY is honest that the built-in security mechanisms are baselines, not
  compliance controls, and names a working report channel.
- No personal email is committed; links resolve.
