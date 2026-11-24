"""Which option contracts the collector records: ATM +- N steps, CE and PE, chosen expiries."""

from collections.abc import Sequence
from datetime import date

from nifty.contracts import Instrument

MAX_INSTRUMENTS = 3000  # per WS connection (spec/08); the index and the future take two more


def needs_recentre(prev_atm: float | None, new_atm: float | None) -> bool:
    """Re-centre when the ATM strike moved (spot moved by one strike step or more)."""
    return new_atm is not None and prev_atm != new_atm


def choose_contracts(
    options: Sequence[Instrument], expiries: Sequence[date], atm_strike: float, step: float,
    window_steps: int, limit: int = MAX_INSTRUMENTS - 2,
) -> list[Instrument]:  # fmt: skip
    lo, hi = atm_strike - window_steps * step, atm_strike + window_steps * step
    want = set(expiries)
    picked = [
        o for o in options
        if o.expiry in want and o.strike is not None and lo - 1e-6 <= o.strike <= hi + 1e-6
        and o.provider_token is not None
    ]  # fmt: skip
    picked.sort(key=lambda o: (o.expiry or date.max, o.strike or 0.0, o.option_type or ""))
    return picked[:limit]


class WindowPlanner:
    """Keeps the recorded set centred on ATM. `update(spot)` returns (to_add, to_remove) when the
    ATM strike moved (by a strike step or more), else None. Contracts leaving the window are
    unsubscribed; their recorded data stays."""

    def __init__(
        self, options: Sequence[Instrument], expiries: Sequence[date], window_steps: int = 5,
        limit: int = MAX_INSTRUMENTS - 2,
    ) -> None:  # fmt: skip
        from nifty.options.chain import atm as _atm
        from nifty.options.chain import strike_step

        self._atm_fn, self._step_fn = _atm, strike_step
        self.options, self.expiries, self.n, self.limit = (
            list(options),
            list(expiries),
            window_steps,
            limit,
        )
        self.atm: float | None = None
        self.current: dict[str, Instrument] = {}

    def update(self, spot: float) -> tuple[list[Instrument], list[Instrument]] | None:
        strikes = [
            o.strike
            for o in self.options
            if o.expiry in set(self.expiries) and o.strike is not None
        ]
        a = self._atm_fn(spot, strikes)
        step = self._step_fn(strikes)
        if a is None or step is None or not needs_recentre(self.atm, a):
            return None
        want = {
            o.instrument_id: o
            for o in choose_contracts(self.options, self.expiries, a, step, self.n, self.limit)
        }
        add = [o for k, o in want.items() if k not in self.current]
        remove = [o for k, o in self.current.items() if k not in want]
        self.atm, self.current = a, want
        return add, remove
