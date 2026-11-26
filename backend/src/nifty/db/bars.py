"""Bar storage: idempotent upsert with revisions, range reads, snapshots."""

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from nifty.contracts import Bar

# Identity of a bar's content. quality_flags and received_at_utc are deliberately excluded so a
# re-import (or a later calendar edit) never creates revisions.
_Key = tuple[float, float, float, float, float, str]


def _key(b: Bar) -> _Key:
    return (b.open, b.high, b.low, b.close, b.volume, b.volume_kind)


@dataclass(frozen=True)
class UpsertResult:
    inserted: int  # new bar_start (revision 0)
    revised: int  # differing content for a known bar_start (revision + 1)
    noop: int  # identical content already stored


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    sha256: str
    n_rows: int
    instrument_id: str
    timeframe: str
    from_utc: datetime
    to_utc: datetime


_INSERT = text(
    """
    INSERT INTO bars (instrument_id, timeframe, bar_start_utc, bar_end_utc, revision, provider,
      open, high, low, close, volume, volume_kind, finalized, received_at_utc, quality_flags)
    VALUES (:instrument_id, :timeframe, :bar_start_utc, :bar_end_utc, :revision, :provider,
      :open, :high, :low, :close, :volume, :volume_kind, :finalized, :received_at_utc,
      CAST(:quality_flags AS text[]))
    ON CONFLICT DO NOTHING
    """
)


def upsert_bars(conn: Connection, bars: Sequence[Bar]) -> UpsertResult:
    groups: dict[tuple[str, str], list[Bar]] = defaultdict(list)
    for b in bars:
        groups[(b.instrument_id, b.timeframe)].append(b)
    inserted = revised = noop = 0
    rows: list[dict[str, Any]] = []
    for (inst, tf), group in groups.items():
        lo = min(b.bar_start_utc for b in group)
        hi = max(b.bar_start_utc for b in group)
        existing: dict[datetime, dict[int, _Key]] = defaultdict(dict)
        for r in conn.execute(
            text(
                "SELECT bar_start_utc, revision, open, high, low, close, volume, volume_kind "
                "FROM bars WHERE instrument_id = :i AND timeframe = :tf "
                "AND bar_start_utc BETWEEN :lo AND :hi"
            ),
            {"i": inst, "tf": tf, "lo": lo, "hi": hi},
        ):
            existing[r[0]][r[1]] = (r[2], r[3], r[4], r[5], r[6], r[7])
        for b in sorted(group, key=lambda x: (x.bar_start_utc, x.revision)):
            known = existing[b.bar_start_utc]
            if _key(b) in known.values():
                noop += 1
                continue
            rev = max(known) + 1 if known else 0
            revised += bool(known)
            inserted += not known
            known[rev] = _key(b)
            row = b.model_dump()
            row["revision"] = rev
            row["quality_flags"] = list(b.quality_flags)
            rows.append(row)
    if rows:
        conn.execute(_INSERT, rows)
    return UpsertResult(inserted=inserted, revised=revised, noop=noop)


_SELECT = """
    SELECT DISTINCT ON (bar_start_utc) instrument_id, provider, timeframe, bar_start_utc,
      bar_end_utc, open, high, low, close, volume, volume_kind, finalized, received_at_utc,
      revision, quality_flags
    FROM bars WHERE instrument_id = :i AND timeframe = :tf
      AND (CAST(:lo AS timestamptz) IS NULL OR bar_start_utc >= :lo)
      AND (CAST(:hi AS timestamptz) IS NULL OR bar_start_utc < :hi)
    ORDER BY bar_start_utc, revision DESC
"""


def read_bars(
    conn: Connection,
    instrument_id: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    last_n: int | None = None,
) -> list[Bar]:
    """Latest revision of each bar in [start, end), ascending. `last_n` keeps the newest N."""
    sql = f"SELECT * FROM ({_SELECT}) t ORDER BY bar_start_utc"
    if last_n is not None:
        sql = f"SELECT * FROM ({sql}) u ORDER BY bar_start_utc DESC LIMIT {int(last_n)}"
    res = conn.execute(
        text(sql), {"i": instrument_id, "tf": timeframe, "lo": start, "hi": end}
    ).mappings()
    bars = [Bar(**{**dict(r), "quality_flags": tuple(r["quality_flags"])}) for r in res]
    return bars[::-1] if last_n is not None else bars


def canonical_rows(bars: Sequence[Bar]) -> str:
    """Sorted rows with fixed float repr; excludes received_at_utc and flags."""
    return "\n".join(
        f"{b.bar_start_utc.astimezone(UTC).isoformat()}|{b.revision}|{b.open!r}|{b.high!r}|"
        f"{b.low!r}|{b.close!r}|{b.volume!r}|{b.volume_kind}"
        for b in sorted(bars, key=lambda x: x.bar_start_utc)
    )


def create_snapshot(
    conn: Connection, instrument_id: str, timeframe: str, from_utc: datetime, to_utc: datetime
) -> Snapshot:
    """Snapshot of the latest revisions in [from_utc, to_utc). Same data => same id."""
    bars = read_bars(conn, instrument_id, timeframe, from_utc, to_utc)
    if not bars:
        raise ValueError("no bars in range")
    sha = hashlib.sha256(canonical_rows(bars).encode()).hexdigest()
    ident = f"{instrument_id}|{timeframe}|{from_utc.astimezone(UTC).isoformat()}|"
    ident += f"{to_utc.astimezone(UTC).isoformat()}|{sha}"
    sid = "snap_" + hashlib.sha256(ident.encode()).hexdigest()[:16]
    conn.execute(
        text(
            "INSERT INTO datasets (snapshot_id, instrument_id, timeframe, from_utc, to_utc, "
            "sha256, n_rows) VALUES (:s, :i, :tf, :f, :t, :sha, :n) ON CONFLICT DO NOTHING"
        ),
        {
            "s": sid,
            "i": instrument_id,
            "tf": timeframe,
            "f": from_utc,
            "t": to_utc,
            "sha": sha,
            "n": len(bars),
        },
    )
    return Snapshot(sid, sha, len(bars), instrument_id, timeframe, from_utc, to_utc)


def latest_bar_start(conn: Connection, instrument_id: str) -> datetime | None:
    """Start of the newest stored bar of an instrument (any timeframe); None when it has none."""
    v = conn.execute(
        text("SELECT max(bar_start_utc) FROM bars WHERE instrument_id = :i"), {"i": instrument_id}
    ).scalar()
    return v if isinstance(v, datetime) else None
