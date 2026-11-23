"""Pine primitives, part 2: stateful incremental indicators.

Each has `update(...) -> value` (NaN while undefined) and `state()` / `load()` with JSON-safe
state (NaN encoded as None). Windowed ones are recomputed over the ring buffer on every bar
(no running sums), so there is no cancellation drift at index-level prices.
"""

import math
from collections import deque
from typing import Any

from nifty.engines.pinekit.core import NaN, dec, enc, pmax


class _Window:
    def __init__(self, length: int) -> None:
        if length < 1:
            raise ValueError("length must be >= 1")
        self.n = length
        self._w: deque[float] = deque(maxlen=length)

    def _push(self, x: float) -> list[float] | None:
        self._w.append(x)
        if len(self._w) < self.n or any(v != v for v in self._w):
            return None
        return list(self._w)

    def state(self) -> dict[str, Any]:
        return {"w": enc(self._w)}

    def load(self, st: dict[str, Any]) -> None:
        self._w.clear()
        self._w.extend(dec(st["w"]))


class Sma(_Window):
    def update(self, x: float) -> float:
        w = self._push(x)
        return NaN if w is None else math.fsum(w) / self.n


class Sum(_Window):
    def update(self, x: float) -> float:
        w = self._push(x)
        return NaN if w is None else math.fsum(w)


class Highest(_Window):
    def update(self, x: float) -> float:
        w = self._push(x)
        return NaN if w is None else max(w)


class Lowest(_Window):
    def update(self, x: float) -> float:
        w = self._push(x)
        return NaN if w is None else min(w)


class Stdev(_Window):
    """Population (biased) standard deviation, as Pine."""

    def update(self, x: float) -> float:
        w = self._push(x)
        if w is None:
            return NaN
        mean = math.fsum(w) / self.n
        return math.sqrt(math.fsum((v - mean) ** 2 for v in w) / self.n)


class Ema:
    """alpha = 2/(len+1). seed='first': first valid value; seed='sma': NaN until len values."""

    def __init__(self, length: int, seed: str = "first") -> None:
        if seed not in ("first", "sma"):
            raise ValueError("seed must be 'first' or 'sma'")
        self.n, self.seed, self.alpha = length, seed, 2.0 / (length + 1)
        self.value = NaN
        self._acc: list[float] = []

    def update(self, x: float) -> float:
        if x != x:
            return NaN  # na source: state untouched
        if self.value == self.value:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        elif self.seed == "first":
            self.value = x
        else:
            self._acc.append(x)
            if len(self._acc) < self.n:
                return NaN
            self.value = math.fsum(self._acc) / self.n
            self._acc = []
        return self.value

    def state(self) -> dict[str, Any]:
        return {"value": enc([self.value])[0], "acc": list(self._acc)}

    def load(self, st: dict[str, Any]) -> None:
        self.value = dec([st["value"]])[0]
        self._acc = list(st["acc"])


class Rma:
    """Wilder: alpha = 1/len, seeded with SMA(len); NaN before."""

    def __init__(self, length: int) -> None:
        self.n = length
        self.value = NaN
        self._acc: list[float] = []

    def update(self, x: float) -> float:
        if x != x:
            return NaN
        if self.value == self.value:
            self.value = (self.value * (self.n - 1) + x) / self.n
        else:
            self._acc.append(x)
            if len(self._acc) < self.n:
                return NaN
            self.value = math.fsum(self._acc) / self.n
            self._acc = []
        return self.value

    def state(self) -> dict[str, Any]:
        return {"value": enc([self.value])[0], "acc": list(self._acc)}

    def load(self, st: dict[str, Any]) -> None:
        self.value = dec([st["value"]])[0]
        self._acc = list(st["acc"])


class Tr:
    """True range; the first bar (no previous close) is high - low."""

    def __init__(self) -> None:
        self.prev_close = NaN

    def update(self, high: float, low: float, close: float, restart: bool = False) -> float:
        if restart or self.prev_close != self.prev_close:
            tr = high - low
        else:
            tr = pmax(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        return tr

    def state(self) -> dict[str, Any]:
        return {"pc": enc([self.prev_close])[0]}

    def load(self, st: dict[str, Any]) -> None:
        self.prev_close = dec([st["pc"]])[0]


class Atr:
    """ta.atr = rma(tr, len). Continuous across sessions."""

    def __init__(self, length: int) -> None:
        self._tr, self._rma = Tr(), Rma(length)

    def update(self, high: float, low: float, close: float) -> float:
        return self._rma.update(self._tr.update(high, low, close))

    def state(self) -> dict[str, Any]:
        return {"tr": self._tr.state(), "rma": self._rma.state()}

    def load(self, st: dict[str, Any]) -> None:
        self._tr.load(st["tr"])
        self._rma.load(st["rma"])


class AtrSess(Atr):
    """Wilder ATR on a session-adjusted TR: the first bar of each session has TR = high - low.

    The smoothing stays continuous across sessions. Distinct from `Atr` on purpose.
    """

    def update(self, high: float, low: float, close: float, new_session: bool = False) -> float:
        return self._rma.update(self._tr.update(high, low, close, restart=new_session))


class Rsi:
    """rma-based RSI. dn == 0 -> 100, then up == 0 -> 0 (so both zero -> 100, as Pine)."""

    def __init__(self, length: int) -> None:
        self._up, self._dn = Rma(length), Rma(length)
        self.prev = NaN

    def update(self, x: float) -> float:
        if self.prev != self.prev:
            self.prev = x
            return NaN
        ch = x - self.prev
        self.prev = x
        up, dn = self._up.update(max(ch, 0.0)), self._dn.update(-min(ch, 0.0))
        if up != up or dn != dn:
            return NaN
        if dn == 0:
            return 100.0
        if up == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + up / dn)

    def state(self) -> dict[str, Any]:
        return {"up": self._up.state(), "dn": self._dn.state(), "prev": enc([self.prev])[0]}

    def load(self, st: dict[str, Any]) -> None:
        self._up.load(st["up"])
        self._dn.load(st["dn"])
        self.prev = dec([st["prev"]])[0]


class _Cross:
    def __init__(self) -> None:
        self.pa, self.pb = NaN, NaN

    def _step(self, a: float, b: float) -> tuple[float, float]:
        prev = (self.pa, self.pb)
        self.pa, self.pb = a, b
        return prev

    def state(self) -> dict[str, Any]:
        return {"a": enc([self.pa])[0], "b": enc([self.pb])[0]}

    def load(self, st: dict[str, Any]) -> None:
        self.pa, self.pb = dec([st["a"], st["b"]])


class Crossover(_Cross):
    def update(self, a: float, b: float) -> bool:
        pa, pb = self._step(a, b)
        return a > b and pa <= pb  # any NaN makes this False


class Crossunder(_Cross):
    def update(self, a: float, b: float) -> bool:
        pa, pb = self._step(a, b)
        return a < b and pa >= pb


class Change:
    """x - x[length]; NaN until enough history."""

    def __init__(self, length: int = 1) -> None:
        self.n = length
        self._w: deque[float] = deque(maxlen=length + 1)

    def update(self, x: float) -> float:
        self._w.append(x)
        return x - self._w[0] if len(self._w) == self.n + 1 else NaN

    def state(self) -> dict[str, Any]:
        return {"w": enc(self._w)}

    def load(self, st: dict[str, Any]) -> None:
        self._w.clear()
        self._w.extend(dec(st["w"]))


class _Pivot:
    """Bar t-right is confirmed at bar t. Candidate must beat the `left` bars before it and
    the `right` bars after it. Ties: 'default' = strict vs left, non-strict vs right
    (Pine-like; the golden decides), 'strict' = strict on both sides."""

    high = True

    def __init__(self, left: int, right: int, pivot_ties: str = "default") -> None:
        if pivot_ties not in ("default", "strict"):
            raise ValueError("pivot_ties must be 'default' or 'strict'")
        self.left, self.right, self.ties = left, right, pivot_ties
        self._w: deque[float] = deque(maxlen=left + right + 1)

    def update(self, x: float) -> float:
        self._w.append(x)
        if len(self._w) < self.left + self.right + 1:
            return NaN
        w = list(self._w)
        c = w[self.left]
        strict_right = self.ties == "strict"
        for v in w[: self.left]:
            if not (c > v if self.high else c < v):
                return NaN
        for v in w[self.left + 1 :]:
            ok = (
                (c > v if strict_right else c >= v)
                if self.high
                else (c < v if strict_right else c <= v)
            )
            if not ok:
                return NaN
        return c

    def state(self) -> dict[str, Any]:
        return {"w": enc(self._w)}

    def load(self, st: dict[str, Any]) -> None:
        self._w.clear()
        self._w.extend(dec(st["w"]))


class PivotHigh(_Pivot):
    high = True


class PivotLow(_Pivot):
    high = False


def round_to_mintick(x: float, mintick: float) -> float:
    """Half-up with an epsilon guard against float noise (verify vs golden)."""
    if x != x:
        return NaN
    return math.floor(x / mintick + 0.5 + 1e-9) * mintick
