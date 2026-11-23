"""BrokerEmulator (tv mode), used by NVS. Spec/03.

Per bar the runner calls `on_bar(bar)` first (pending market orders fill at the open, then the
bracket resolves along the assumed path, possibly on the entry bar), then the script runs at the
close and queues new orders. No pyramiding, margin or bar magnifier; fixed qty; commission is a
percent of fill value per side.

Timestamps: open and intrabar-level fills use the bar start; close fills use the bar end.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nifty.contracts import Bar, TradeRecord
from nifty.execution.barriers import step_bar

Side = Literal["long", "short"]


@dataclass
class Position:
    side: Side
    qty: float
    entry_px: float
    entry_time: datetime
    signal_bar_start: datetime | None
    bars_held: int = 0
    mae: float = 0.0
    mfe: float = 0.0


@dataclass
class _Order:
    kind: Literal["entry", "close"]
    side: Side | None
    reason: str
    signal_bar_start: datetime | None


@dataclass
class _Bracket:
    stop: float | None
    limit: float | None
    for_pending: bool  # placed together with a not-yet-filled entry


class BrokerEmulator:
    def __init__(
        self,
        engine_id: str,
        instrument_id: str,
        qty: float = 1.0,
        commission_pct: float = 0.0,
    ) -> None:
        self.engine_id, self.instrument_id = engine_id, instrument_id
        self.qty, self.commission_pct = qty, commission_pct
        self._pos: Position | None = None
        self._visible: Side | None = None
        self._pending: list[_Order] = []
        self._bracket: _Bracket | None = None
        self._bar: Bar | None = None
        self._n = 0

    # ---- script-facing state ------------------------------------------------------------
    @property
    def position(self) -> Side | None:
        """Position as the script sees it at this bar (an `immediately` close shows at t+1)."""
        return self._visible

    @property
    def actual_position(self) -> Position | None:
        return self._pos

    # ---- orders (queued at bar close, filled from the next bar) ------------------------------
    def entry(
        self, side: Side, signal_bar_start: datetime | None = None, reason: str = "REVERSE"
    ) -> None:
        self._pending.append(_Order("entry", side, reason, signal_bar_start))

    def close(self, reason: str = "SIGNAL", immediately: bool = False) -> TradeRecord | None:
        if immediately:
            return self._fill_close_now(reason)
        self._pending.append(_Order("close", None, reason, None))
        return None

    def close_all(self, reason: str = "SIGNAL", immediately: bool = False) -> TradeRecord | None:
        return self.close(reason, immediately)  # single position model

    def exit(self, stop: float | None = None, limit: float | None = None) -> None:
        """Bracket (OCO). Replaces any previous bracket. Ignored when flat with nothing pending."""
        has_entry = any(o.kind == "entry" for o in self._pending)
        if self._pos is None and not has_entry:
            return
        self._bracket = _Bracket(stop, limit, for_pending=self._pos is None or has_entry)

    # ---- per-bar processing ---------------------------------------------------------------
    def on_bar(self, bar: Bar) -> list[TradeRecord]:
        self._bar = bar
        closed: list[TradeRecord] = []
        orders, self._pending = self._pending, []
        for o in orders:
            if o.kind == "close":
                if self._pos is not None:
                    closed.append(self._close_pos(bar.open, bar.bar_start_utc, o.reason, bar))
            elif o.side is not None:
                if self._pos is not None and self._pos.side == o.side:
                    continue  # no pyramiding
                if self._pos is not None:
                    closed.append(self._close_pos(bar.open, bar.bar_start_utc, "REVERSE", bar))
                self._open(o.side, bar, o.signal_bar_start)
        if self._pos is not None:
            p = self._pos
            p.bars_held += 1
            br = self._bracket
            out = step_bar(
                p.side, p.entry_px, br.stop if br else None, br.limit if br else None, bar, "tv"
            )
            p.mae, p.mfe = max(p.mae, out.mae), max(p.mfe, out.mfe)
            if out.reason is not None:
                reason = out.reason
                closed.append(self._close_pos(out.px, bar.bar_start_utc, reason, bar, out.flags))
        self._visible = self._pos.side if self._pos else None
        return closed

    # ---- internals ----------------------------------------------------------------------------
    def _open(self, side: Side, bar: Bar, signal: datetime | None) -> None:
        self._pos = Position(side, self.qty, bar.open, bar.bar_start_utc, signal)
        if self._bracket is not None:
            self._bracket.for_pending = False

    def _fill_close_now(self, reason: str) -> TradeRecord | None:
        if self._pos is None or self._bar is None:
            return None
        return self._close_pos(self._bar.close, self._bar.bar_end_utc, reason, self._bar)

    def _close_pos(
        self, px: float, when: datetime, reason: str, bar: Bar, flags: list[str] | None = None
    ) -> TradeRecord:
        p = self._pos
        assert p is not None
        s = 1.0 if p.side == "long" else -1.0
        gross = s * (px - p.entry_px)
        cost = (p.entry_px + px) * self.commission_pct / 100.0
        self._n += 1
        self._pos = None
        if self._bracket is not None and not self._bracket.for_pending:
            self._bracket = None
        return TradeRecord(
            trade_id=f"{self.engine_id}:{self._n}",
            engine_id=self.engine_id,
            instrument_id=self.instrument_id,
            side=p.side,
            signal_bar_start=p.signal_bar_start,
            entry_time=p.entry_time,
            entry_px=p.entry_px,
            exit_time=when,
            exit_px=px,
            exit_reason=reason,
            qty=p.qty,
            gross_pts=gross,
            cost_pts=cost,
            net_pts=gross - cost,
            mae_pts=p.mae,
            mfe_pts=p.mfe,
            bars_held=max(p.bars_held, 1),
            execution_mode="tv",
            flags=list(flags or []),
        )
