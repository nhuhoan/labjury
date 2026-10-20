# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for an undisclosed vulnerability.**

Report it privately through GitHub's **Security Advisories** on the repository
(*Security → Report a vulnerability*), which opens a private channel with the
maintainers. Include the affected version/commit, a description, and ideally a minimal
reproduction. We aim to acknowledge a report within a few days and will coordinate a
fix and disclosure timeline with you.

## Supported versions

LabJury is pre-1.0. Security fixes are made against the latest `main`; there is no
back-porting to older tags yet. Pin a commit you have reviewed if you need stability
before 1.0.

## Security posture — read this before you rely on the built-ins

LabJury ships **mechanisms and zero-dependency baselines**, not turnkey compliance
controls. Understanding the line matters for a correct deployment:

- **PII redaction** (`RegexRedactor`) is a baseline that masks obvious email/phone/card
  patterns in text. It is **not** a compliance control and misses names, addresses,
  non-text modalities, and obfuscated data. The `Redactor` seam is where you plug your
  own detector appropriate to your jurisdiction (GDPR ≠ CCPA ≠ local law). See
  [docs/pii-redaction.md](docs/pii-redaction.md).
- **Prompt-injection guards** (`HeuristicInjectionGuard`) are best-effort, additive
  defense that match a few known override phrases. They are **not** a real
  injection defense; the `Guard` seam is for your own detector. See
  [docs/prompt-injection.md](docs/prompt-injection.md).
- **Secrets** (`Secret`) is **leak-resistance, not encryption**: it keeps a credential
  out of `repr`/`str`/logs/JSON, but `reveal()` returns plaintext and it is not a
  secret manager. Bring your own vault. See [docs/secrets.md](docs/secrets.md).

The framework's own guarantees are narrow and deliberate: the audit trail records
content **fingerprints, never raw content**; the engine stores no credentials (plugins
receive configured clients by injection); and remote-plugin wrappers fail **closed**.
Everything else — storage, transport, access control, key management — is the
deployer's infrastructure.
