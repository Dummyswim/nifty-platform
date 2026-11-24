"""Instrument master (D10): parse the daily dump and derive facts from it only (never hardcode
expiries, strikes steps, lot or tick sizes)."""

import csv
import io
from datetime import date

from nifty.contracts import Instrument
from nifty.marketdata.base import ErrorCode, ProviderError

COLUMNS = [
    "instrument_token", "exchange_token", "tradingsymbol", "name", "last_price", "expiry",
    "strike", "tick_size", "lot_size", "instrument_type", "segment", "exchange",
]  # fmt: skip
UNDERLYING = "NIFTY"  # the dump's `name` for NIFTY index derivatives


def instrument_id(exchange: str, tradingsymbol: str) -> str:
    return f"kite:{exchange}:{tradingsymbol}"


def parse_master(text: str, version: str | None = None) -> list[Instrument]:
    """The rows we use: NSE index rows (e.g. NIFTY 50) and NFO NIFTY futures/options. Other rows
    (equities, other underlyings) stay in the stored raw dump only."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or any(c not in reader.fieldnames for c in COLUMNS):
        raise ProviderError(ErrorCode.BAD_DATA, "instrument dump has unexpected columns")
    out: list[Instrument] = []
    for r in reader:
        typ, seg, exch = r["instrument_type"], r["segment"], r["exchange"]
        is_index = seg == "INDICES" and exch == "NSE"
        is_deriv = exch == "NFO" and r["name"] == UNDERLYING and typ in ("FUT", "CE", "PE")
        if not (is_index or is_deriv):
            continue
        try:
            expiry = date.fromisoformat(r["expiry"]) if r["expiry"] else None
            out.append(
                Instrument(
                    instrument_id=instrument_id(exch, r["tradingsymbol"]),
                    provider="kite",
                    provider_token=int(r["instrument_token"]),
                    exchange=exch,
                    segment=seg,
                    instrument_type="INDEX" if is_index else typ,  # type: ignore[arg-type]
                    tradingsymbol=r["tradingsymbol"],
                    underlying=None if is_index else UNDERLYING,
                    expiry=expiry,
                    strike=float(r["strike"])
                    if is_deriv and typ != "FUT" and r["strike"]
                    else None,
                    option_type=typ if typ in ("CE", "PE") else None,  # type: ignore[arg-type]
                    tick_size=float(r["tick_size"])
                    if r["tick_size"] and float(r["tick_size"]) > 0
                    else None,  # index rows list 0
                    lot_size=int(r["lot_size"])
                    if r["lot_size"] and int(r["lot_size"]) > 0
                    else None,
                    metadata_version=version,
                    provider_meta={"exchange_token": r["exchange_token"], "name": r["name"]},
                )
            )
        except (ValueError, KeyError) as e:
            raise ProviderError(
                ErrorCode.BAD_DATA, f"bad instrument row {r.get('tradingsymbol')}"
            ) from e
    return out


def nifty_index(ins: list[Instrument]) -> Instrument | None:
    return next(
        (i for i in ins if i.instrument_type == "INDEX" and i.tradingsymbol == "NIFTY 50"), None
    )


def expiries(ins: list[Instrument], kind: str) -> list[date]:
    return sorted({i.expiry for i in ins if i.instrument_type == kind and i.expiry})


def front_month_future(ins: list[Instrument], today: date) -> Instrument | None:
    """Nearest-expiry NIFTY future not yet expired: the proxy-volume source (D10, C09-C11)."""
    futs = [i for i in ins if i.instrument_type == "FUT" and i.expiry and i.expiry >= today]
    return min(futs, key=lambda i: i.expiry or date.max, default=None)


def option_universe(
    ins: list[Instrument], expiry: date | None = None, option_type: str | None = None,
    strike: float | None = None,
) -> list[Instrument]:  # fmt: skip
    return sorted(
        (
            i
            for i in ins
            if i.instrument_type in ("CE", "PE")
            and (expiry is None or i.expiry == expiry)
            and (option_type is None or i.option_type == option_type)
            and (strike is None or i.strike == strike)
        ),
        key=lambda i: (i.expiry or date.max, i.strike or 0.0, i.option_type or ""),
    )


def strike_step(ins: list[Instrument], expiry: date) -> float | None:
    """Smallest gap between listed strikes of an expiry (derived, D10)."""
    ks = sorted({i.strike for i in option_universe(ins, expiry) if i.strike is not None})
    gaps = [b - a for a, b in zip(ks, ks[1:], strict=False)]
    return min(gaps) if gaps else None
