"""Acceptance numbers for reference/oracle/data/nifty_1m.csv (docs/SOURCES.md quirks)."""

from datetime import date

from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.timeutil import IST
from tests.helpers import CAL, ORACLE


def test_oracle_quirks() -> None:
    bars = parse_csv(ORACLE, instrument_id="csv:NIFTY 50")
    ok, r = validate_bars(bars, CAL)
    assert (r.rows_in, r.rows_ok, len(ok)) == (5997, 5996, 5996)
    assert [(e.ts.astimezone(IST).isoformat(), e.reason) for e in r.excluded] == [
        ("2026-11-16T14:49:50+05:30", "off_grid")
    ]
    assert len(r.sessions) == 17
    first, last = r.sessions[0], r.sessions[-1]
    assert (first.first.astimezone(IST).strftime("%H:%M"), first.n) == ("14:50", 40)
    assert (last.last.astimezone(IST).strftime("%H:%M"), last.n) == ("14:48", 334)
    assert [(g.day, g.missing, g.from_ts.astimezone(IST).strftime("%H:%M")) for g in r.gaps] == [
        (date(2026, 10, 26), 1, "14:49"),
        (date(2026, 11, 2), 1, "14:49"),
        (date(2026, 11, 9), 1, "14:49"),
    ]
    assert sorted(s.n for s in r.sessions if s.n not in (40, 334, 375)) == [374, 374, 374]
    assert r.volume_kind == "absent" and r.calendar_unverified
    assert all(b.volume_kind == "absent" and "volume_absent" in b.quality_flags for b in ok)
    assert (r.duplicates, r.out_of_order) == (0, 0)
