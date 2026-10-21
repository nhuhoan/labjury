"""Token/$ cost metering — a side channel the scorer reports into.

The model's token usage originates *inside* a scorer's ``score()`` call; the
:class:`~labjury.observability.Observer` hooks only receive an ``ItemResult`` and
never see token counts. Rather than break the ``Scorer``/``Observer``/``ItemResult``
contract, a deployer injects a :class:`CostMeter` into their scorer and reports
usage directly (see ``docs/cost-metering.md``). This complements
:class:`~labjury.observability.PerTenantUsage` (counts + latency); here it is
tokens and dollars, both keyed by tenant.

LabJury owns the *counting* and the tokens×rate *arithmetic*; the deployer owns the
*rate* (pricing is per-model, per-contract policy) and the *reporting* (only their
scorer knows its model's token accounting). ``record()`` has no ``await``, so it is
atomic within one asyncio event loop — like ``InMemoryObserver``, it is not a
cross-OS-thread counter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    """Accumulated token usage, and the dollar arithmetic over a deployer's rate.

    ``cost`` multiplies by per-1000-token rates the deployer supplies — the rate is
    their pricing policy, the multiply is ours."""

    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def cost(self, in_per_1k: float, out_per_1k: float) -> float:
        return self.tokens_in / 1000 * in_per_1k + self.tokens_out / 1000 * out_per_1k


class CostMeter:
    """A side-channel accumulator a scorer reports token usage into, per tenant.

    Untagged traffic (``tenant is None``) lands in its own bucket. Mirrors
    :class:`~labjury.observability.PerTenantUsage` in shape: ``for_tenant`` never
    inserts or raises, ``snapshot`` hands back a copy."""

    def __init__(self) -> None:
        self._by: dict[str | None, list[int]] = {}  # tenant -> [in, out, calls]

    def record(
        self, tokens_in: int = 0, tokens_out: int = 0, *, tenant: str | None = None
    ) -> None:
        """Report one scorer call's token usage for ``tenant``."""
        bucket = self._by.setdefault(tenant, [0, 0, 0])
        bucket[0] += tokens_in
        bucket[1] += tokens_out
        bucket[2] += 1

    def for_tenant(self, tenant: str | None) -> TokenUsage:
        """This tenant's usage, or a fresh zero tally — never inserts or raises."""
        bucket = self._by.get(tenant)
        return TokenUsage(*bucket) if bucket is not None else TokenUsage()

    def total(self) -> TokenUsage:
        """Usage summed across every tenant (including the untagged bucket)."""
        return TokenUsage(
            sum(b[0] for b in self._by.values()),
            sum(b[1] for b in self._by.values()),
            sum(b[2] for b in self._by.values()),
        )

    def snapshot(self) -> dict[str | None, TokenUsage]:
        """A fresh mapping of fresh ``TokenUsage`` values — the caller cannot use it
        to mutate the meter."""
        return {tenant: TokenUsage(*bucket) for tenant, bucket in self._by.items()}
