"""Leak-resistant credential holder — zero-dependency.

LabJury never stores or asks for credentials: plugins receive already-configured
clients by dependency injection. :class:`Secret` guards against the other
failure — *leaking* a key through a log line, a traceback, or the one audit path
that records plugin config (``ProvenanceRef.params``, serialized verbatim).

Wrap a credential in ``Secret`` and its value never shows in ``repr()``,
``str()``, an f-string, or ``json.dumps`` (which raises instead of serializing —
a leak into a store fails loud). Read it only at the point of use with
``reveal()``. This is leak-resistance against accidental disclosure, **not**
encryption: ``reveal()`` returns the plaintext.
"""

from __future__ import annotations


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the underlying value — the only way to read it."""
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)
