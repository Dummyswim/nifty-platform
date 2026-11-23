"""Pine primitives, part 1: na handling, Series, JSON-safe state encoding. Plain floats (D27)."""

import math
from collections import deque
from collections.abc import Iterable

NaN = math.nan


def isna(x: float) -> bool:
    return x != x


def nz(x: float, d: float = 0.0) -> float:
    return d if x != x else x


def pmax(*xs: float) -> float:
    """Pine max: NaN-propagating (Python's max(1, nan) would silently return 1)."""
    if any(x != x for x in xs):
        return NaN
    return max(xs)


def pmin(*xs: float) -> float:
    if any(x != x for x in xs):
        return NaN
    return min(xs)


def enc(xs: Iterable[float]) -> list[float | None]:
    """NaN -> None so snapshots survive json.dumps(allow_nan=False)."""
    return [None if x != x else x for x in xs]


def dec(xs: Iterable[float | None]) -> list[float]:
    return [NaN if x is None else x for x in xs]


class Series:
    """Ring buffer with Pine indexing: s[0] is the current value, s[n] is n bars back."""

    def __init__(self, maxlen: int) -> None:
        self._buf: deque[float] = deque(maxlen=maxlen)

    def push(self, x: float) -> None:
        self._buf.append(x)

    def __getitem__(self, n: int) -> float:
        return self._buf[-1 - n] if 0 <= n < len(self._buf) else NaN

    def __len__(self) -> int:
        return len(self._buf)

    def state(self) -> dict[str, object]:
        return {"buf": enc(self._buf)}

    def load(self, st: dict[str, object]) -> None:
        self._buf.clear()
        self._buf.extend(dec(st["buf"]))  # type: ignore[arg-type]
