"""Session-anchored resampling (D08). Pure and deterministic.

Buckets start at the session open and never straddle sessions. Incomplete buckets are
emitted with `partial_bucket` (clipped by the session end, or data missing at either end)
and `gap_before` (holes inside). A bucket is `finalized` when all inputs are finalized and
its last input bar is present or a later input bar exists.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from nifty.contracts import TF_MINUTES, Bar
from nifty.timeutil import Calendar

_MIN = timedelta(minutes=1)


def resample(bars: Sequence[Bar], tf: str, cal: Calendar | None = None) -> list[Bar]:
    if not bars:
        return []
    cal = cal or Calendar.load()
    in_tf = bars[0].timeframe
    if any(b.timeframe != in_tf for b in bars):
        raise ValueError("input must be a single timeframe")
    if in_tf == "1d":
        if tf != "1d":
            raise ValueError("cannot resample 1d to a shorter timeframe")
        return sorted(bars, key=lambda b: b.bar_start_utc)
    if len({b.instrument_id for b in bars}) > 1:
        raise ValueError("mixed instruments")
    in_min = TF_MINUTES[in_tf]
    is_day = tf == "1d"
    tgt_min = 0 if is_day else TF_MINUTES[tf]
    if not is_day and (tgt_min < in_min or tgt_min % in_min):
        raise ValueError(f"cannot resample {in_tf} to {tf}")

    ordered = sorted(bars, key=lambda b: b.bar_start_utc)
    if len({b.bar_start_utc for b in ordered}) != len(ordered):
        raise ValueError("duplicate bar_start_utc; pass one revision per bar")
    last_start = ordered[-1].bar_start_utc

    groups: dict[tuple[date, datetime], list[Bar]] = defaultdict(list)
    bounds: dict[date, tuple[datetime, datetime]] = {}
    extent: dict[date, list[datetime]] = {}  # per session: [first bar start, last bar end]
    for b in ordered:
        d = cal.session_date(b.bar_start_utc)
        open_, close = bounds.setdefault(d, cal.session_bounds(d))
        if not open_ <= b.bar_start_utc < close:
            raise ValueError(f"bar {b.bar_start_utc} outside session; validate first")
        idx = 0 if is_day else int((b.bar_start_utc - open_) / _MIN) // tgt_min
        groups[(d, open_ + idx * tgt_min * _MIN)].append(b)
        ext = extent.setdefault(d, [b.bar_start_utc, b.bar_end_utc])
        ext[1] = b.bar_end_utc

    out: list[Bar] = []
    for (d, start), members in sorted(groups.items(), key=lambda kv: kv[0][1]):
        close = bounds[d][1]
        nominal_end = close if is_day else start + tgt_min * _MIN
        end = min(nominal_end, close)
        last_end = members[-1].bar_end_utc
        s_first, s_last_end = extent[d]
        present = {m.bar_start_utc for m in members}
        # missing slots inside the session's data extent are gaps; slots outside it are a
        # partial bucket (session truncated by the data or clipped by the session close)
        holes = 0
        t = start
        while t < end:
            holes += t not in present and s_first < t and t + in_min * _MIN < s_last_end
            t += in_min * _MIN
        partial = nominal_end > close or start < s_first or end > s_last_end
        flags = {f for m in members for f in m.quality_flags}
        if partial:
            flags.add("partial_bucket")
        if holes:
            flags.add("gap_before")
        kinds = {m.volume_kind for m in members}
        kind = (
            next(iter(kinds))
            if len(kinds) == 1
            else next(k for k in sorted(kinds) if k != "absent")
        )
        out.append(
            Bar(
                instrument_id=members[0].instrument_id,
                provider=members[0].provider,
                timeframe=tf,  # type: ignore[arg-type]
                bar_start_utc=start,
                bar_end_utc=end,
                open=members[0].open,
                high=max(m.high for m in members),
                low=min(m.low for m in members),
                close=members[-1].close,
                volume=sum(m.volume for m in members),
                volume_kind=kind,
                finalized=all(m.finalized for m in members)
                and (last_end >= end or last_start >= end),
                received_at_utc=max(m.received_at_utc for m in members),
                quality_flags=tuple(sorted(flags)),
            )
        )
    return out
