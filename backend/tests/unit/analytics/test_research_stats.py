"""C14 statistics: split/purge, session-clustered bootstrap, leave-one-session-out, verdict table."""

from datetime import UTC, date, datetime, timedelta

from nifty.analytics import research as rs
from nifty.contracts import TradeRecord

D0 = date(2026, 1, 1)
HOLD = timedelta(minutes=10)


def days(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def at(d: date, h: int = 10, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)


def tr(
    d: date, net: float, k: int = 0, reason: str = "TARGET_FIRST", flags: list[str] | None = None
) -> TradeRecord:
    e = at(d, 10 + k)
    return TradeRecord(
        trade_id=f"{d}-{k}", engine_id="e", instrument_id="i", side="long", signal_bar_start=e - timedelta(minutes=1),
        entry_time=e, entry_px=100.0, exit_time=e + timedelta(minutes=5), exit_px=100.0 + net, exit_reason=reason,
        gross_pts=net, net_pts=net, r_multiple=net / 12, flags=flags or [],
    )  # fmt: skip


def session_of(t: datetime) -> date:
    return t.date()


def bounds(sessions: list[date]) -> dict[str, datetime]:
    a = rs.split_sessions(sessions)
    return {sp: at(next(s for s in sessions if a[s] == sp), 0) for sp in rs.SPLITS}


def test_split_sizes_and_order() -> None:
    a = rs.split_sessions(days(17))
    cnt = {sp: sum(1 for v in a.values() if v == sp) for sp in rs.SPLITS}
    assert cnt == {"dev": 9, "val": 4, "eval": 4}  # floor(8.5+.5), floor(12.75+.5)
    assert [a[d] for d in days(17)] == ["dev"] * 9 + ["val"] * 4 + ["eval"] * 4  # chronological
    b = rs.split_sessions(days(80))
    assert sum(v == "dev" for v in b.values()) == 40 and sum(v == "val" for v in b.values()) == 20


def test_purge_drops_trades_reaching_the_next_split() -> None:
    ss = days(8)  # dev 4, val 2, eval 2
    bd = bounds(ss)
    assign = rs.split_sessions(ss)
    last_dev = ss[3]
    near = tr(last_dev, 1.0)  # entry 10:00, exit 10:05 on its own day: well before the val boundary
    reaching = near.model_copy(
        update={"exit_time": at(ss[4], 0, 5)}
    )  # still open past the val start
    kept, dropped = rs.purge([near, reaching], assign, session_of, bd, HOLD)
    assert kept == [near] and dropped == [reaching]
    # the nominal max hold alone also reaches the boundary
    late = near.model_copy(
        update={"entry_time": at(last_dev, 23, 55), "exit_time": at(last_dev, 23, 58)}
    )
    kept, dropped = rs.purge([late], assign, session_of, bd, HOLD)
    assert dropped == [late]


def test_no_leakage_between_splits_after_purge() -> None:
    ss = days(20)
    bd = bounds(ss)
    assign = rs.split_sessions(ss)
    trades = [tr(d, 1.0, k) for d in ss for k in range(2)]
    kept, _ = rs.purge(trades, assign, session_of, bd, HOLD)
    nxt = {"dev": "val", "val": "eval"}
    for t in kept:
        sp = assign[t.entry_time.date()]
        if sp in nxt:
            assert max(t.exit_time, t.entry_time + HOLD) < bd[nxt[sp]]


def test_bootstrap_resamples_whole_sessions_only() -> None:
    by = {date(2026, 1, 1): [10.0, 10.0], date(2026, 1, 2): [-4.0]}
    point, lo, hi, means = rs.bootstrap_ci(by, seed=7, resamples=500, return_samples=True)  # type: ignore[misc]
    assert abs(point - 16 / 3) < 1e-12  # (10 + 10 - 4) / 3
    # Draws of 2 sessions: AA -> 10, AB/BA -> 16/3, BB -> -4. A trade-level resample would produce 3, 8, ...
    allowed = (10.0, 16 / 3, -4.0)
    assert all(any(abs(m - a) < 1e-9 for a in allowed) for m in means)
    assert lo == -4.0 and hi == 10.0


def test_bootstrap_is_deterministic_and_seed_dependent() -> None:
    by = {d: [float(i % 5) - 1.5, 2.0] for i, d in enumerate(days(12))}
    a = rs.bootstrap_ci(by, 3)
    assert a == rs.bootstrap_ci(by, 3)
    assert a != rs.bootstrap_ci(by, 4)
    assert rs.bootstrap_ci({}, 3)[0] != rs.bootstrap_ci({}, 3)[0]  # NaN, no trades


def test_leave_one_session_out_hand_checked() -> None:
    d1, d2, d3 = days(3)
    got = dict(rs.leave_one_out({d1: [10.0], d2: [20.0], d3: [-6.0]}))
    assert got == {d1: 7.0, d2: 2.0, d3: 15.0}  # (20-6)/2, (10-6)/2, (10+20)/2


def test_outcome_mix_counts_ambiguous_and_interrupted() -> None:
    d = days(1)[0]
    ts = [
        tr(d, 10.0, 0),
        tr(d, -12.0, 1, "STOP_FIRST", ["ambiguous_bar"]),
        tr(d, 0.0, 2, "TIME_EXIT", ["session_cut"]),
        tr(d, 1.0, 3, "TIME_EXIT", ["data_gap"]),
    ]
    assert rs.outcome_mix(ts) == {
        "n": 4, "TARGET_FIRST": 1, "STOP_FIRST": 1, "TIME_EXIT": 2, "ambiguous": 1, "interrupted": 2,
    }  # fmt: skip


def build(n_sessions: int, nets: tuple[float, float]) -> tuple[list[TradeRecord], list[date]]:
    ss = days(n_sessions)
    out = []
    for i, d in enumerate(ss):
        a, b = nets if i % 2 == 0 else nets[::-1]
        out += [tr(d, a, 0), tr(d, b, 1)]
    return out, ss


def verdict_for(trades: list[TradeRecord], ss: list[date]) -> dict:  # type: ignore[type-arg]
    ev = rs.evaluate(trades, ss, session_of, bounds(ss), HOLD, seed=1, resamples=400)
    return rs.verdict(ev, len(ss))


def test_strong_edge_at_80_sessions_is_a_candidate() -> None:
    trades, ss = build(80, (6.0, 4.0))
    v = verdict_for(trades, ss)
    assert v["verdict"] == "candidate" and all(c["passed"] for c in v["conditions"])


def test_noise_at_80_sessions_is_edge_not_established() -> None:
    trades, ss = build(80, (10.0, -10.0))  # exactly zero expectancy
    v = verdict_for(trades, ss)
    assert v["verdict"] == "edge_not_established"
    assert not next(c for c in v["conditions"] if "CI lower" in c["name"])["passed"]


def test_17_sessions_is_inconclusive_even_with_a_strong_edge() -> None:
    trades, ss = build(17, (6.0, 4.0))
    v = verdict_for(trades, ss)
    assert v["verdict"] == "inconclusive" and v["reason"] == "insufficient sessions"
    assert not next(c for c in v["conditions"] if "sessions" in c["name"])["passed"]
    top = rs.run_verdict([{"verdict": v}], 17)
    assert top["verdict"] == "inconclusive" and "insufficient sessions" in top["reason"]


def test_one_bad_session_breaks_loso() -> None:
    trades, ss = build(80, (6.0, 4.0))
    ev_sessions = [d for d, s in rs.split_sessions(ss).items() if s == "eval"]
    trades = [
        t.model_copy(update={"net_pts": -1.0, "gross_pts": -1.0})
        if t.entry_time.date() in ev_sessions
        else t
        for t in trades
    ]
    trades.append(tr(ev_sessions[0], 500.0, 5))
    v = verdict_for(trades, ss)
    assert v["verdict"] == "edge_not_established"
    assert not next(c for c in v["conditions"] if "leave-one" in c["name"])["passed"]
