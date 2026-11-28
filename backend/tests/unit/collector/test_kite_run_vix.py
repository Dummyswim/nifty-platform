from nifty.collector.kite_run import vix_index
from nifty.contracts import Instrument


def _idx(sym: str, token: int | None, exchange: str = "NSE") -> Instrument:
    return Instrument(
        instrument_id=f"kite:{exchange}:{sym}",
        provider="kite",
        provider_token=token,
        exchange=exchange,
        segment="INDICES",
        instrument_type="INDEX",
        tradingsymbol=sym,
    )


def test_vix_index_picks_the_vix_row() -> None:
    ins = [_idx("NIFTY 50", 1), _idx("INDIA VIX", 2), _idx("SENSEX", 3, "BSE")]
    got = vix_index(ins)
    assert got is not None and got.instrument_id == "kite:NSE:INDIA VIX"


def test_vix_index_absent() -> None:
    assert vix_index([_idx("NIFTY 50", 1), _idx("SENSEX", 3, "BSE")]) is None


def test_vix_index_without_token() -> None:
    assert vix_index([_idx("INDIA VIX", None)]) is None


def test_vix_index_ignores_non_nse() -> None:
    assert vix_index([_idx("INDIA VIX", 2, "BSE")]) is None
