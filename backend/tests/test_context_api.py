"""Context API on a seeded nifty_test: NIFTY spot, INDIA VIX history and a falling session where
puts are written (OI up, IV easing) and calls are bought (OI up, IV rising)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from nifty.api import context_routes
from nifty.contracts import Bar, Instrument
from nifty.db.bars import upsert_bars
from nifty.db.chart import set_pref
from nifty.db.context import load_day
from nifty.db.instruments import upsert_instrument
from nifty.options.bs import bs, years_to_expiry
from nifty.timeutil import IST

pytestmark = pytest.mark.db
H = {"Origin": "http://127.0.0.1:8080"}
DAY = date(2026, 11, 26)  # Thursday, a weekday session
PRIOR = [date(2026, 11, 25), date(2026, 11, 24), date(2026, 11, 23)]  # newest first
EXPIRY = date(2026, 12, 1)  # weekly (Tuesday)
STRIKES = [25_850.0 + 50 * i for i in range(7)]  # ATM 26000 +- 3 steps
SPOT_ID, VIX_ID = "kite:NSE:NIFTY 50", "kite:NSE:INDIA VIX"
R, SIGMA = 0.065, 0.15
RECV = datetime(2026, 11, 26, 12, tzinfo=UTC)


def _bar(iid: str, start: datetime, close: float) -> Bar:
    return Bar(
        instrument_id=iid, provider="kite", timeframe="1m", bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=1), open=close, high=close, low=close, close=close,
        volume=0, received_at_utc=RECV,
    )  # fmt: skip


def _minutes(d: date, n: int, at: time = time(9, 15)) -> list[datetime]:
    t0 = datetime.combine(d, at, tzinfo=IST).astimezone(UTC)
    return [t0 + timedelta(minutes=i) for i in range(n)]


def _cid(k: float, ot: str) -> str:
    return f"kite:NFO:NIFTY{EXPIRY:%y%m%d}{int(k)}{ot}"


def seed(conn: Connection) -> None:
    upsert_instrument(conn, Instrument(instrument_id=SPOT_ID, provider="kite",
                                       tradingsymbol="NIFTY 50"))  # fmt: skip
    upsert_instrument(conn, Instrument(instrument_id=VIX_ID, provider="kite",
                                       tradingsymbol="INDIA VIX"))  # fmt: skip
    for k in STRIKES:
        for ot in ("CE", "PE"):
            upsert_instrument(conn, Instrument(
                instrument_id=_cid(k, ot), provider="kite", instrument_type=ot,
                tradingsymbol=_cid(k, ot).split(":")[-1], underlying="NIFTY", expiry=EXPIRY,
                strike=k, option_type=ot,
            ))  # fmt: skip
    bars: list[Bar] = []
    ticks: list[dict[str, Any]] = []
    # 260 prior VIX sessions (one close each, all below today's 15.0 -> rank 100)
    d, n = DAY, 0
    while n < 260:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            bars.append(_bar(VIX_ID, _minutes(d, 1, time(15, 29))[0], 11.0 + (n % 30) * 0.1))
            n += 1
    sessions = [(DAY, 60, 26_000.0, -0.5)] + [(p, 10, 26_050.0, 0.3) for p in PRIOR]
    for sd, n_min, s0, drift in sessions:
        for i, m in enumerate(_minutes(sd, n_min)):
            s = s0 + drift * i
            bars.append(_bar(SPOT_ID, m, s))
            if sd == DAY:
                bars.append(_bar(VIX_ID, m, 15.0))
            t = years_to_expiry(EXPIRY, m + timedelta(minutes=1))
            for k in STRIKES:
                for ot in ("CE", "PE"):
                    sigma = SIGMA
                    if sd == DAY:
                        sigma = 0.16 + 0.0002 * i if ot == "CE" else SIGMA - 0.0001 * i
                    g = bs(s, k, t, R, sigma, ot == "CE")
                    assert g is not None
                    bars.append(_bar(_cid(k, ot), m, g.price))
                    if sd == DAY:  # OI up on both sides; only the puts' IV eases
                        oi = 100_000 + (1_000 if ot == "CE" else 500) * i
                    elif sd == PRIOR[0]:
                        oi = 90_000 if ot == "CE" else 100_000
                    else:
                        continue
                    ticks.append({
                        "i": _cid(k, ot), "te": m + timedelta(seconds=30),
                        "tr": m + timedelta(seconds=31), "ltp": g.price, "v": 0, "oi": oi,
                        "b": None, "a": None, "bq": None, "aq": None,
                    })  # fmt: skip
    upsert_bars(conn, bars)
    conn.execute(
        text(
            "INSERT INTO ticks (instrument_id, ts_exchange, ts_received, ltp, volume_traded, oi, "
            "bid, ask, bid_qty, ask_qty) VALUES (:i, :te, :tr, :ltp, :v, :oi, :b, :a, :bq, :aq)"
        ),
        ticks,
    )
    set_pref(conn, "options.r", R)


@pytest.fixture
def seeded(api: tuple[TestClient, Engine]) -> Iterator[tuple[TestClient, Engine]]:
    c, eng = api
    with eng.begin() as conn:
        seed(conn)
    context_routes.clear_cache()
    yield c, eng
    context_routes.clear_cache()


def _get(c: TestClient, **params: str) -> Any:
    r = c.get("/api/v1/context", params={"date": DAY.isoformat(), **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_context_bias_on_seeded_day(seeded: Any) -> None:
    c, _ = seeded
    body = _get(c)
    now = datetime.now(UTC).timestamp()
    assert body["underlying"] == "NIFTY" and body["date"] == DAY.isoformat()
    assert body["expiry"] == EXPIRY.isoformat()
    s = body["series"]
    assert len(s) == 60 and all(x["t"] < now for x in s)
    last = s[-1]
    assert last["na_reason"] is None and last["vix_rank"] == 100.0 and last["vix_high"] is True
    assert last["pe"]["verdict"] == "FAIR" and last["pe"]["iv"] == pytest.approx(14.41, abs=0.1)
    assert body["writing"] == "iv" and all(x["writing"] == "iv" for x in s)
    assert all(x["w_day"] == 1.0 for x in s[1:])  # put writing only: calls were bought
    assert last["ce"]["own_iv"] == pytest.approx(15.0, abs=0.1)  # 3 prior sessions with bars
    assert last["rv"] is not None and body["params"]["band_pct"] == 10
    assert all(x["flags"] == [] for x in s) and body["notes"] == []
    assert _get(c) == body  # served again (cached) unchanged


def test_context_oi_rule_differs_on_seeded_day(seeded: Any) -> None:
    c, _ = seeded
    iv, oi = _get(c), _get(c, writing="oi")
    assert oi["writing"] == "oi" and all(x["writing"] == "oi" for x in oi["series"])
    assert oi["params"]["writing"] == "oi" and iv["params"]["writing"] == "iv"
    last = oi["series"][-1]
    d_ce, d_pe = 10_000 + 1_000 * 59.0, 500 * 59.0  # CE prev OI 90k, PE 100k
    assert (last["oi_ce"], last["oi_pe"]) == (6 * d_ce, 6 * d_pe)  # ATM 25950: 25850..26100
    assert last["w_day"] == pytest.approx((d_pe - d_ce) / (d_pe + d_ce))
    assert last["bias"] == "BEARISH" and iv["series"][-1]["bias"] != "BEARISH"
    assert _get(c) == iv  # the cache keeps the two rules apart


def test_context_unknown_writing_422(seeded: Any) -> None:
    c, _ = seeded
    r = c.get("/api/v1/context", params={"date": DAY.isoformat(), "writing": "xx"})
    assert r.status_code == 422


def test_context_per_rule_prefs(seeded: Any) -> None:
    c, eng = seeded
    with eng.begin() as conn:
        set_pref(conn, "context", {"w_exit": 0.05})
        set_pref(conn, "context.oi", {"w_min": 0.1})
    iv, oi = _get(c)["params"], _get(c, writing="oi")["params"]
    assert (iv["w_min"], iv["w_exit"]) == (0.3, 0.05)
    assert (oi["w_min"], oi["w_exit"]) == (0.1, 0.05)


def test_context_without_rate(seeded: Any) -> None:
    c, eng = seeded
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM prefs WHERE key = 'options.r'"))
    s = _get(c)["series"]
    assert s and all(x["ce"]["iv"] is None for x in s)
    assert all(x["na_reason"] == "IV n/a: set rate in Settings" for x in s)


def test_context_bad_params_422(seeded: Any) -> None:
    c, eng = seeded
    with eng.begin() as conn:
        set_pref(conn, "context", {"band_pct": 10, "exit_pct": 5})
    r = c.get("/api/v1/context", params={"date": DAY.isoformat()})
    assert r.status_code == 422 and "invalid context prefs" in r.text


def test_context_no_session(seeded: Any) -> None:
    c, _ = seeded
    body = _get(c, date="2026-11-28")  # Saturday
    assert body["series"] == [] and body["expiry"] is None
    assert body["notes"] == ["no session data for 2026-11-28"]


def test_context_unknown_underlying(seeded: Any) -> None:
    c, _ = seeded
    assert c.get("/api/v1/context", params={"underlying": "SENSEX"}).status_code == 404
    c.cookies.clear()
    assert c.get("/api/v1/context").status_code == 401


def test_load_day_has_no_lookahead(seeded: Any) -> None:
    _, eng = seeded
    now = datetime.combine(DAY, time(9, 45), tzinfo=IST).astimezone(UTC)
    last = now - timedelta(minutes=1)  # the 09:44 bar is the last one closed by 09:45
    with eng.connect() as conn:
        inp = load_day(conn, "NIFTY", DAY, now)
    assert inp.minutes and inp.minutes[-1] == last and len(inp.minutes) == 30
    assert max(inp.spot) == last and max(inp.vix) == last
    assert inp.options and all(o.close and max(o.close) == last for o in inp.options)
    assert all(o.oi and max(o.oi) == last for o in inp.options)  # tick 09:44:30 <= now
    assert inp.prev_session_close_at == datetime(2026, 11, 25, 10, tzinfo=UTC)  # 15:30 IST
