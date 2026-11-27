"""Loads one session's `DayInputs` for the context series. Only closed data (bar end / tick <= now)."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Any

from sqlalchemy import Connection, text

from nifty.context.series import DayInputs, OptSeries, atm_side_iv, choose_expiry
from nifty.context.vol import realised_vol
from nifty.db.chart import get_prefs
from nifty.timeutil import IST, Calendar

_SESSION_DAY = "CAST(b.bar_start_utc AT TIME ZONE 'Asia/Kolkata' AS date)"
_VIX_SESSIONS = 252
_RV_SESSIONS = 20
_OWN_IV_SESSIONS, _OWN_IV_MIN = 5, 3
_BAR = timedelta(minutes=1)


def _bounds(d: date) -> tuple[datetime, datetime]:
    """IST calendar day [00:00, 24:00) in UTC."""
    lo = datetime.combine(d, time(0), tzinfo=IST).astimezone(UTC)
    return lo, lo + timedelta(days=1)


def _index_id(conn: Connection, symbol: str) -> str | None:
    """The index with 1m bars, Kite first (same preference as `db.options.spot`)."""
    return conn.execute(
        text(
            "SELECT i.instrument_id FROM instruments i WHERE i.tradingsymbol = :s "
            "AND i.instrument_type = 'INDEX' AND EXISTS (SELECT 1 FROM bars b "
            "WHERE b.instrument_id = i.instrument_id AND b.timeframe = '1m') "
            "ORDER BY (i.provider = 'kite') DESC, i.instrument_id LIMIT 1"
        ),
        {"s": symbol},
    ).scalar()


def _closes(
    conn: Connection, iid: str, lo: datetime, hi: datetime, now: datetime
) -> dict[datetime, float]:
    """1m closes (latest revision) keyed by bar start, bars in [lo, hi) that ended by now."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (bar_start_utc) bar_start_utc, close FROM bars "
            "WHERE instrument_id = :i AND timeframe = '1m' AND bar_start_utc >= :lo "
            "AND bar_start_utc < :hi AND bar_end_utc <= :now ORDER BY bar_start_utc, revision DESC"
        ),
        {"i": iid, "lo": lo, "hi": hi, "now": now},
    )
    return {r[0]: float(r[1]) for r in rows}


def _session_closes(conn: Connection, iid: str, before: date, n: int) -> list[tuple[date, float]]:
    """Last 1m close of each of the newest n sessions before `before`, newest first. Reads a
    bounded window: n sessions span about n*7/5 calendar days, plus 30 days of holiday slack."""
    hi = _bounds(before)[0]
    rows = conn.execute(
        text(
            f"SELECT DISTINCT ON (d) d, close FROM (SELECT {_SESSION_DAY} AS d, b.bar_start_utc, "
            "b.revision, b.close FROM bars b WHERE b.instrument_id = :i AND b.timeframe = '1m' "
            "AND b.bar_start_utc >= :lo AND b.bar_start_utc < :hi) t "
            "ORDER BY d DESC, bar_start_utc DESC, revision DESC LIMIT :n"
        ),
        {"i": iid, "lo": hi - timedelta(days=n * 7 // 5 + 30), "hi": hi, "n": n},
    )
    return [(r[0], float(r[1])) for r in rows]


def _recorded_options(
    conn: Connection, underlying: str, d: date, now: datetime
) -> dict[str, tuple[float, bool, date]]:  # fmt: skip
    """Contracts with 1m bars on d: id -> (strike, is_call, expiry)."""
    lo, hi = _bounds(d)
    rows = conn.execute(
        text(
            "SELECT i.instrument_id, i.strike, i.option_type, i.expiry FROM instruments i "
            "WHERE i.instrument_type IN ('CE', 'PE') AND i.underlying = :u "
            "AND i.strike IS NOT NULL AND i.expiry IS NOT NULL AND EXISTS (SELECT 1 FROM bars b "
            "WHERE b.instrument_id = i.instrument_id AND b.timeframe = '1m' "
            "AND b.bar_start_utc >= :lo AND b.bar_start_utc < :hi AND b.bar_end_utc <= :now)"
        ),
        {"u": underlying, "lo": lo, "hi": hi, "now": now},
    )
    return {r[0]: (float(r[1]), r[2] == "CE", r[3]) for r in rows}


def _option_closes(
    conn: Connection, ids: list[str], d: date, now: datetime
) -> dict[str, dict[datetime, float]]:  # fmt: skip
    lo, hi = _bounds(d)
    out: dict[str, dict[datetime, float]] = defaultdict(dict)
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (instrument_id, bar_start_utc) instrument_id, bar_start_utc, close "
            "FROM bars WHERE instrument_id = ANY(:ids) AND timeframe = '1m' "
            "AND bar_start_utc >= :lo AND bar_start_utc < :hi AND bar_end_utc <= :now "
            "ORDER BY instrument_id, bar_start_utc, revision DESC"
        ),
        {"ids": ids, "lo": lo, "hi": hi, "now": now},
    )
    for r in rows:
        out[r[0]][r[1]] = float(r[2])
    return out


def _oi(
    conn: Connection, ids: list[str], d: date, now: datetime
) -> dict[str, dict[datetime, float]]:
    """Last recorded OI per minute (keyed by minute start), same shape as `db.options.oi_series`."""
    lo, hi = _bounds(d)
    out: dict[str, dict[datetime, float]] = defaultdict(dict)
    rows = conn.execute(
        text(
            "SELECT instrument_id, date_trunc('minute', ts_exchange) AS m, "
            "(array_agg(oi ORDER BY ts_exchange DESC))[1] FROM ticks "
            "WHERE instrument_id = ANY(:ids) AND oi IS NOT NULL AND ts_exchange >= :lo "
            "AND ts_exchange < :hi AND ts_exchange <= :now GROUP BY instrument_id, m"
        ),
        {"ids": ids, "lo": lo, "hi": hi, "now": now},
    )
    for r in rows:
        out[r[0]][r[1]] = float(r[2])
    return out


def _prev_values(
    conn: Connection, ids: list[str], prev: date | None
) -> tuple[dict[str, float], dict[str, float]]:  # fmt: skip
    """(last bar close, last tick OI) per contract on the previous session date."""
    if prev is None or not ids:
        return {}, {}
    lo, hi = _bounds(prev)
    p = {"ids": ids, "lo": lo, "hi": hi}
    closes = conn.execute(
        text(
            "SELECT DISTINCT ON (instrument_id) instrument_id, close FROM bars "
            "WHERE instrument_id = ANY(:ids) AND timeframe = '1m' AND bar_start_utc >= :lo "
            "AND bar_start_utc < :hi ORDER BY instrument_id, bar_start_utc DESC, revision DESC"
        ),
        p,
    )
    ois = conn.execute(
        text(
            "SELECT DISTINCT ON (instrument_id) instrument_id, oi FROM ticks "
            "WHERE instrument_id = ANY(:ids) AND oi IS NOT NULL AND ts_exchange >= :lo "
            "AND ts_exchange < :hi ORDER BY instrument_id, ts_exchange DESC"
        ),
        p,
    )
    return {r[0]: float(r[1]) for r in closes}, {r[0]: float(r[1]) for r in ois}


def _session_atm_iv(
    conn: Connection, underlying: str, spot_id: str, d: date, now: datetime, r: float
) -> dict[bool, float] | None:  # fmt: skip
    """Median ATM IV per side over one session's minutes; None when the day has no option bars."""
    rec = _recorded_options(conn, underlying, d, now)
    if not rec:
        return None
    expiry = choose_expiry(d, sorted({e for _, _, e in rec.values()}))
    ids = [i for i, (_, _, e) in rec.items() if e == expiry]
    if expiry is None or not ids:
        return {}
    closes = _option_closes(conn, ids, d, now)
    spot = _closes(conn, spot_id, *_bounds(d), now)
    out: dict[bool, float] = {}
    for is_call in (True, False):
        by_min: dict[datetime, dict[float, float]] = defaultdict(dict)
        for i in ids:
            k, call, _ = rec[i]
            if call == is_call:
                for m, c in closes.get(i, {}).items():
                    by_min[m][k] = c
        ivs = [
            iv
            for m, s in spot.items()
            if m in by_min
            and (iv := atm_side_iv(s, by_min[m], expiry, m + _BAR, r, is_call)) is not None
        ]
        if ivs:
            out[is_call] = median(ivs)
    return out


def _own_iv(
    conn: Connection, underlying: str, spot_id: str, prior: list[date], now: datetime,
    r: float | None,
) -> dict[tuple[str, bool], float]:  # fmt: skip
    if r is None:
        return {}
    per_side: dict[bool, list[float]] = {True: [], False: []}
    found = 0
    for d in prior:  # newest first; skip days without option bars
        day_iv = _session_atm_iv(conn, underlying, spot_id, d, now, r)
        if day_iv is None:
            continue
        for is_call, v in day_iv.items():
            per_side[is_call].append(v)
        found += 1
        if found == _OWN_IV_SESSIONS:
            break
    return {("weekly", k): median(v) for k, v in per_side.items() if len(v) >= _OWN_IV_MIN}


def _num(v: Any, default: float | None) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def load_day(
    conn: Connection, underlying: str, day: date, now: datetime,
    prefs: dict[str, Any] | None = None,
) -> DayInputs:  # fmt: skip
    """One session's inputs; only minutes whose bar end <= now. `prefs` defaults to stored prefs."""
    prefs = get_prefs(conn) if prefs is None else prefs
    r = _num(prefs.get("options.r"), None)
    max_stale_s = _num(prefs.get("options.max_stale_s"), 60.0)
    window_steps = int(_num(prefs.get("options.window_steps"), 5) or 5)
    assert max_stale_s is not None
    spot_id = _index_id(conn, "NIFTY 50")
    vix_id = _index_id(conn, "INDIA VIX")
    lo, hi = _bounds(day)
    spot = _closes(conn, spot_id, lo, hi, now) if spot_id else {}
    prior = _session_closes(conn, spot_id, day, _RV_SESSIONS) if spot_id else []
    prev = prior[0][0] if prior else None
    vix = _closes(conn, vix_id, lo, hi, now) if vix_id else {}
    vix_prior = _session_closes(conn, vix_id, day, _VIX_SESSIONS) if vix_id else []

    rv = None
    if spot_id and prior:
        hist = _closes(conn, spot_id, _bounds(prior[-1][0])[0], lo, now)
        by_day: dict[date, list[float]] = defaultdict(list)
        for m in sorted(hist):
            by_day[Calendar.session_date(m)].append(hist[m])
        rv = realised_vol([by_day[d] for d in sorted(by_day)])

    rec = _recorded_options(conn, underlying, day, now)
    ids = list(rec)
    closes = _option_closes(conn, ids, day, now) if ids else {}
    ois = _oi(conn, ids, day, now) if ids else {}
    prev_c, prev_oi = _prev_values(conn, ids, prev)
    options = [
        OptSeries(
            strike=k,
            is_call=call,
            expiry=e,
            close=closes.get(i, {}),
            oi=ois.get(i, {}),
            prev_close=prev_c.get(i),
            prev_oi=prev_oi.get(i),
        )  # fmt: skip
        for i, (k, call, e) in rec.items()
    ]
    own = _own_iv(conn, underlying, spot_id, [d for d, _ in prior], now, r) if spot_id else {}
    return DayInputs(
        day=day, minutes=sorted(spot), spot=spot,
        prev_spot_close=prior[0][1] if prior else None, vix=vix,
        vix_prior_closes=[c for _, c in reversed(vix_prior)], own_iv=own, rv=rv, r=r,
        max_stale_s=max_stale_s, expiries=sorted({e for _, _, e in rec.values()}),
        options=options, window_steps=window_steps,
    )  # fmt: skip


def last_closed_minute(conn: Connection, day: date, now: datetime) -> datetime | None:
    """Newest NIFTY 50 1m bar start on `day` whose bar has ended by now (the cache key)."""
    spot_id = _index_id(conn, "NIFTY 50")
    if spot_id is None:
        return None
    lo, hi = _bounds(day)
    return conn.execute(
        text(
            "SELECT max(bar_start_utc) FROM bars WHERE instrument_id = :i AND timeframe = '1m' "
            "AND bar_start_utc >= :lo AND bar_start_utc < :hi AND bar_end_utc <= :now"
        ),
        {"i": spot_id, "lo": lo, "hi": hi, "now": now},
    ).scalar()


def session_for(conn: Connection, cal: Calendar, day: date | None, now: datetime) -> date | None:
    """`day` when it is a session day with NIFTY bars; by default today if so, else the last
    session with NIFTY bars."""
    if day is not None:
        ok = cal.is_session_day(day) and last_closed_minute(conn, day, now) is not None
        return day if ok else None
    today = Calendar.session_date(now)
    if cal.is_session_day(today) and last_closed_minute(conn, today, now) is not None:
        return today
    spot_id = _index_id(conn, "NIFTY 50")
    if spot_id is None:
        return None
    for d, _ in _session_closes(conn, spot_id, today, 10):
        if cal.is_session_day(d):
            return d
    return None
