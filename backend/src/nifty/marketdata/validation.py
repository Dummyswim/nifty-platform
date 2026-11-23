"""Bar validation shared by the importer and the collector. Pure; never silently repairs."""

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from nifty.contracts import (
    TF_MINUTES,
    Bar,
    Exclusion,
    Gap,
    SessionInfo,
    ValidationReport,
)
from nifty.timeutil import Calendar


def _row_error(b: Bar) -> str | None:
    px = (b.open, b.high, b.low, b.close)
    if not all(math.isfinite(p) for p in px):
        return "non_finite"
    if b.low > min(b.open, b.close) or b.high < max(b.open, b.close):
        return "bad_ohlc"
    if not math.isfinite(b.volume) or b.volume < 0:
        return "bad_volume"
    return None


def _grid_error(b: Bar, cal: Calendar) -> str | None:
    t = b.bar_start_utc
    if t.second or t.microsecond:
        return "off_grid"
    d = cal.session_date(t)
    if not cal.is_session_day(d):
        return "non_session_day"
    open_, close = cal.session_bounds(d)
    if not open_ <= t < close:
        return "off_session"
    if b.timeframe == "1d":
        return None if t == open_ else "off_grid"
    if (t - open_) % timedelta(minutes=TF_MINUTES[b.timeframe]):
        return "off_grid"
    return None


def validate_bars(
    bars: Sequence[Bar], cal: Calendar | None = None
) -> tuple[list[Bar], ValidationReport]:
    """Return accepted bars (sorted, revisions assigned) and the report."""
    cal = cal or Calendar.load()
    tfs = {b.timeframe for b in bars}
    if len(tfs) > 1:
        raise ValueError(f"mixed timeframes: {sorted(tfs)}")
    excluded: list[Exclusion] = []
    seen: dict[datetime, list[tuple[float, ...]]] = defaultdict(list)
    kept: list[Bar] = []
    duplicates = out_of_order = 0
    prev: datetime | None = None
    for b in bars:
        reason = _grid_error(b, cal) or _row_error(b)
        if reason:
            excluded.append(Exclusion(ts=b.bar_start_utc, reason=reason))
            continue
        if prev is not None and b.bar_start_utc < prev:
            out_of_order += 1
        prev = b.bar_start_utc
        ohlcv = (b.open, b.high, b.low, b.close, b.volume)
        if ohlcv in seen[b.bar_start_utc]:
            duplicates += 1
            continue
        rev = len(seen[b.bar_start_utc])
        seen[b.bar_start_utc].append(ohlcv)
        kept.append(b.model_copy(update={"revision": rev}))
    kept.sort(key=lambda b: (b.bar_start_utc, b.revision))

    by_day: dict[date, list[datetime]] = defaultdict(list)
    for t in sorted(seen):
        by_day[cal.session_date(t)].append(t)

    gaps: list[Gap] = []
    sessions: list[SessionInfo] = []
    after_gap: set[datetime] = set()
    for day in sorted(by_day):
        starts = by_day[day]
        sessions.append(SessionInfo(date=day, first=starts[0], last=starts[-1], n=len(starts)))
        if not kept or kept[0].timeframe == "1d":
            continue
        step = timedelta(minutes=TF_MINUTES[kept[0].timeframe])
        present = set(starts)
        run: list[datetime] = []
        t = starts[0]
        while t <= starts[-1]:
            if t not in present:
                run.append(t)
            elif run:
                gaps.append(Gap(day=day, from_ts=run[0], to_ts=run[-1], missing=len(run)))
                after_gap.add(t)
                run = []
            t += step

    volume_absent = bool(kept) and all(b.volume == 0 for b in kept)
    out: list[Bar] = []
    for b in kept:
        flags = set(b.quality_flags)
        if b.bar_start_utc in after_gap:
            flags.add("gap_before")
        update: dict[str, object] = {}
        if volume_absent:
            flags.add("volume_absent")
            update["volume_kind"] = "absent"
        update["quality_flags"] = tuple(sorted(flags))
        out.append(b.model_copy(update=update))

    report = ValidationReport(
        rows_in=len(bars),
        rows_ok=len(out),
        excluded=excluded,
        gaps=gaps,
        duplicates=duplicates,
        out_of_order=out_of_order,
        sessions=sessions,
        volume_kind="absent" if volume_absent else (out[0].volume_kind if out else "exchange"),
        calendar_unverified=any(not cal.is_verified(s.date) for s in sessions),
    )
    return out, report
