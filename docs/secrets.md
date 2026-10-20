# Secrets — a no-store guarantee and a leak-resistant holder

LabJury's plugins talk to remote models (Jev, an LLM judge, ASR) with API keys.
The framework's stance has two halves: it never **stores** credentials, and it
helps you not **leak** them.

## The no-store guarantee

- LabJury core never asks for, reads, or holds a credential. Plugins receive
  already-configured clients by dependency injection — you construct the client
  with your key and hand LabJury the plugin.
- The audit trail records content *fingerprints*, never raw content (see
  [audit-trail.md](audit-trail.md)).
- The source of truth for secrets is **your** infrastructure — Vault, a cloud
  secret manager, k8s secrets, environment variables. LabJury neither reads nor
  manages it, and ships no secret store (the same "bring your own storage" rule
  as everywhere else).

## The one real leak path

There is exactly one LabJury-owned path that records plugin configuration:
`ProvenanceRef.params` on an `AuditEvent` captures "how a plugin was configured"
and is serialized verbatim into whatever audit store you plug in. A raw key
dropped into those params leaks into that store.

The fix is `labjury.Secret`: wrap any sensitive config value in it. Its value
never appears in `repr()`, `str()`, an f-string, or `json.dumps` — serialization
raises `TypeError` instead, so a leak into a store **fails loud** rather than
silently writing the key.

## `Secret` usage

```python
import os
import labjury as lj

key = lj.Secret(os.environ["JEV_API_KEY"])

# masked everywhere it might be logged or recorded
print(key)            # ***
repr(key)             # "Secret('***')"
f"configured with {key}"   # "configured with ***"

# read it only at the point of use
client = JevClient(api_key=key.reveal())
```

`Secret` compares and hashes by value (only against another `Secret`), so it is
safe to keep in config dicts and sets.

## What this is not

- **Not a secret store or manager.** No Vault/cloud integration, no env-var
  loading, no rotation — that is your infrastructure.
- **Not automatic scrubbing.** `Secret` is opt-in at the value level; LabJury
  cannot rewrite a third-party plugin's own exception text or logs.
- **Not encryption.** `Secret` resists accidental disclosure (repr/str/serialize);
  `reveal()` returns the plaintext. It is not a cryptographic container.
