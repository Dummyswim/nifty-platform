"""CE/PE paper mapping of an index trade on RECORDED data only (D12).

Policy is applied at ENTRY time: BUY -> CE, SELL -> PE (long premium), strike type + expiry kind
resolved from the contracts listed then. Entry at the recorded ASK of the last tick <= entry time,
exit at the recorded BID of the last tick <= exit time, both no older than `max_stale_s`; otherwise
the trade is skipped and counted as `no_quote`. Units never mix: premiums `Prem`, money `Inr`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nifty.contracts import Instrument, TradeRecord
from nifty.contracts.units import Inr, Prem
from nifty.options.bs import effective_today
from nifty.options.chain import DEFAULT_OFFSETS, atm, expiry_kinds, strike_for, strike_step

CLOCK_EXITS = {"EOD", "TIME", "SESSION_END"}  # everything else is decided by the index


@dataclass(frozen=True)
class Policy:
    strike_type: str = "ATM"
    expiry_kind: str = "current weekly"
    lots: int = 1
    cost_inr: float = 0.0  # explicit round-trip cost, shown in reports
    max_stale_s: float = 60.0


@dataclass(frozen=True)
class Quote:
    ts: datetime
    bid: float | None
    ask: float | None
    ltp: float | None = None


class QuoteBook(Protocol):
    def last_quote(self, contract_id: str, at: datetime) -> Quote | None: ...


def pick_contract(
    options: Sequence[Instrument], is_long: bool, spot: float, at: datetime, policy: Policy,
    offsets: dict[str, int] | None = None,
) -> Instrument | None:  # fmt: skip
    opt = "CE" if is_long else "PE"
    mine = [o for o in options if o.option_type == opt and o.expiry and o.strike is not None]
    expiry = expiry_kinds([o.expiry for o in mine if o.expiry], effective_today(at))[
        policy.expiry_kind
    ]
    if expiry is None:
        return None
    strikes = [o.strike for o in mine if o.expiry == expiry and o.strike is not None]
    step = strike_step(strikes)
    a = atm(spot, strikes)
    if step is None or a is None:
        return None
    k = strike_for(policy.strike_type, opt, a, step, strikes, offsets or DEFAULT_OFFSETS)
    return next((o for o in mine if o.expiry == expiry and o.strike == k), None)


def map_trade(
    trade: TradeRecord, options: Sequence[Instrument], quotes: QuoteBook, policy: Policy,
    offsets: dict[str, int] | None = None,
) -> tuple[TradeRecord | None, str | None]:  # fmt: skip
    """(option trade, None) or (None, reason) with reason `no_contract` | `no_quote`."""
    c = pick_contract(
        options, trade.side == "long", trade.entry_px, trade.entry_time, policy, offsets
    )
    if c is None or not c.lot_size:
        return None, "no_contract"
    cid = c.instrument_id
    q_in, q_out = quotes.last_quote(cid, trade.entry_time), quotes.last_quote(cid, trade.exit_time)

    def fresh(q: Quote | None, at: datetime, px: float | None) -> bool:
        return (
            q is not None
            and px is not None
            and px > 0
            and (at - q.ts).total_seconds() <= policy.max_stale_s
        )

    if not (fresh(q_in, trade.entry_time, q_in.ask if q_in else None)
            and fresh(q_out, trade.exit_time, q_out.bid if q_out else None)):  # fmt: skip
        return None, "no_quote"
    assert q_in is not None and q_out is not None and q_in.ask is not None and q_out.bid is not None
    entry, exit_ = Prem(q_in.ask), Prem(q_out.bid)  # buy at the ask, sell at the bid
    gross = Inr((exit_ - entry) * policy.lots * c.lot_size)
    pnl = gross - Inr(policy.cost_inr)
    outlay = entry * policy.lots * c.lot_size
    return trade.model_copy(
        update={
            "contract_id": cid,
            "entry_prem": float(entry),
            "exit_prem": float(exit_),
            "pnl_inr": float(pnl),
            "roi_pct": float(pnl) / outlay * 100.0,
            "synthetic": trade.exit_reason not in CLOCK_EXITS,
            "flags": [*trade.flags, "option_paper"],
        }
    ), None
