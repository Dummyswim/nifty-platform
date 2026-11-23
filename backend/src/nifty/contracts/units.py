"""Unit-tagged floats. Mixing different units in + or - raises UnitMismatch.

typing.NewType has no runtime effect, so these are tiny float subclasses. They are for
boundaries and reporting; the per-bar hot path uses plain floats (D27).
"""

from typing import Self


class UnitMismatch(TypeError):
    pass


class _Unit(float):
    __slots__ = ()

    def _check(self, other: object) -> None:
        if isinstance(other, _Unit) and type(other) is not type(self):
            raise UnitMismatch(f"{type(self).__name__} vs {type(other).__name__}")

    def __add__(self, other: float) -> Self:
        self._check(other)
        return type(self)(float.__add__(self, other))

    def __radd__(self, other: float) -> Self:
        self._check(other)
        return type(self)(float.__add__(self, other))

    def __sub__(self, other: float) -> Self:
        self._check(other)
        return type(self)(float.__sub__(self, other))

    def __rsub__(self, other: float) -> Self:
        self._check(other)
        return type(self)(float.__rsub__(self, other))


class Pts(_Unit):
    """Index points."""


class Prem(_Unit):
    """Option premium."""


class Inr(_Unit):
    """Rupees."""


class R(_Unit):
    """R multiples."""


class Bps(_Unit):
    """Basis points."""
