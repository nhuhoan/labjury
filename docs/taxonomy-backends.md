# Taxonomy backends — bring your own

LabJury's taxonomy is the open-world vocabulary of labels: a label is
*proposed* when first seen, and *promoted* to official by a human. Where that
state lives is entirely up to you. `RedisTaxonomyStore` is **one reference
backend, not a requirement** — the same way `Jev` is just one `Scorer`.

If your company runs Cassandra, DynamoDB, Postgres, or an in-house key-value
store, you can back the taxonomy with it by writing a small class. **No
inheritance, no base class, no change to LabJury core.**

## The contract

A taxonomy backend is any object with these five `async` methods (this is the
`labjury.plugins.TaxonomyStore` protocol):

```python
async def is_known(self, label: str) -> bool: ...          # True only after promote
async def propose(self, label: str, meta: dict | None = None) -> None: ...
async def promote(self, label: str) -> None: ...           # proposed -> official
async def known_labels(self) -> set[str]: ...              # the official tier
async def proposed_labels(self) -> set[str]: ...           # the pending tier
```

The open-world invariants every backend must honor:

- a label is unknown until `promote` — `propose` alone never makes `is_known`
  return `True`;
- `promote` works whether or not the label was proposed first;
- proposing an already-official label is a no-op;
- `known_labels` and `proposed_labels` reflect exactly the two tiers.

`meta` is accepted for forward compatibility; a backend may persist or ignore
it.

## Writing one

```python
class MyTaxonomyStore:
    def __init__(self, db):
        self._db = db

    async def is_known(self, label):
        return await self._db.exists("official", label)

    async def propose(self, label, meta=None):
        if not await self._db.exists("official", label):
            await self._db.add("proposed", label)

    async def promote(self, label):
        await self._db.move("proposed", "official", label)

    async def known_labels(self):
        return await self._db.members("official")

    async def proposed_labels(self):
        return await self._db.members("proposed")
```

Pass it straight to the engine:

```python
engine = lj.Engine(..., taxonomy=MyTaxonomyStore(db))
```

## Prove it — the conformance suite

Don't guess whether your backend behaves correctly. LabJury ships the exact
suite its own stores are tested with. Run it against yours:

```python
from labjury.testing import assert_taxonomy_store_contract

async def test_my_store_is_a_valid_taxonomy():
    await assert_taxonomy_store_contract(lambda: MyTaxonomyStore(fresh_db()))
```

The factory must return a *fresh, empty* store each call. If the suite passes,
your backend is a drop-in replacement for `InMemoryTaxonomyStore` and the
reference `RedisTaxonomyStore`.

## The Redis reference backend

If Redis suits you, it comes batteries-included:

```bash
pip install labjury[redis]
```

```python
import redis.asyncio as aioredis
from labjury.contrib.redis_taxonomy import RedisTaxonomyStore

client = aioredis.from_url("redis://localhost:6379", decode_responses=True)
taxonomy = RedisTaxonomyStore(client, namespace="labjury:tax")
engine = lj.Engine(..., taxonomy=taxonomy)
```

The client is injected — LabJury never opens or owns the connection, so
pooling, TLS, and failover stay yours. `namespace` isolates independent
taxonomies on one Redis.
