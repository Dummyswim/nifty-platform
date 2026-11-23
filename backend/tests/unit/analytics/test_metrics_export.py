"""Metrics on hand-computed fixtures and the export formats."""

import csv
import io
import json
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from nifty.analytics.export import COLUMNS, to_csv, to_json, to_xlsx
from nifty.analytics.metrics import compute_metrics
from nifty.contracts import TradeRecord

T0 = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)  # 09:30 IST


def trade(i: int, net: float, day: int = 0, reason: str = "TP") -> TradeRecord:
    ex = T0 + timedelta(days=day, minutes=5 * i)
    return TradeRecord(
        trade_id=f"t{i}", engine_id="e", instrument_id="i", side="long", entry_time=ex - timedelta(minutes=5),
        entry_px=100.0, exit_time=ex, exit_px=100.0 + net, exit_reason=reason, gross_pts=net,
        net_pts=net, r_multiple=net / 10,
    )  # fmt: skip


def sess(ts: datetime) -> date:
    return ts.date()


def test_metrics_hand_computed() -> None:
    # net: +10 -5 -5 +20 -2 -3 -1 +4  -> cum 10 5 0 20 18 15 14 18
    nets = [10, -5, -5, 20, -2, -3, -1, 4]
    ts = [trade(i, n, day=i // 2) for i, n in enumerate(nets)]  # 4 sessions, 2 trades each
    m = compute_metrics(ts, sess)
    assert (m["n_trades"], m["wins"], m["losses"]) == (8, 3, 5)
    assert m["win_rate"] == pytest.approx(3 / 8)
    assert m["gross_profit_pts"] == 34 and m["gross_loss_pts"] == -16
    assert m["profit_factor"] == pytest.approx(34 / 16)
    assert m["total_pnl_pts"] == 18 and m["expectancy_pts"] == pytest.approx(18 / 8)
    assert m["max_drawdown_pts"] == 10  # 10 -> 0 (later 20 -> 14 is only 6)
    assert (m["max_consecutive_wins"], m["max_consecutive_losses"]) == (1, 3)  # -5 -5 | -2 -3 -1
    # per session: +5, +15, -5, +3 -> mean 4.5, sample sd = sqrt(((.5)^2+10.5^2+9.5^2+1.5^2)/3)
    sd = math.sqrt((0.25 + 110.25 + 90.25 + 2.25) / 3)
    assert m["n_sessions"] == 4 and m["low_n"] is True and "low_n" in m["flags"]
    assert m["sharpe"] == pytest.approx(4.5 / sd * math.sqrt(252))


def test_no_losses_and_empty_and_flat() -> None:
    m = compute_metrics([trade(0, 5), trade(1, 3, day=1)], sess)
    assert m["profit_factor"] is None and "no_losses" in m["flags"] and m["max_drawdown_pts"] == 0
    e = compute_metrics([], sess)
    assert e["n_trades"] == 0 and e["win_rate"] is None and e["sharpe"] is None
    flat = compute_metrics([trade(0, 2), trade(1, 0), trade(2, 2)], sess)
    assert flat["max_consecutive_wins"] == 1  # a flat trade breaks the streak


def test_zero_trade_sessions_count_for_sharpe() -> None:
    ts = [trade(0, 10), trade(1, 10, day=1)]
    days = [T0.date() + timedelta(days=i) for i in range(4)]
    m = compute_metrics(ts, sess, days)
    assert m["n_sessions"] == 4  # [10, 10, 0, 0]
    assert m["sharpe"] == pytest.approx(5 / math.sqrt(100 / 3) * math.sqrt(252))
    assert (
        compute_metrics(ts, sess)["sharpe"] is None
        and "zero_variance" in compute_metrics(ts, sess)["flags"]
    )


def test_exports_have_units_and_same_rows() -> None:
    ts = [trade(0, 5, reason="TP"), trade(1, -3, reason="SL")]
    summ = compute_metrics(ts, sess)
    rows = list(csv.DictReader(io.StringIO(to_csv(ts))))
    assert len(rows) == 2 and list(rows[0]) == [h for h, _ in COLUMNS]
    numeric = [
        h
        for h, k in COLUMNS
        if k.endswith(("_px", "_pts", "_prem", "_inr", "_pct", "r_multiple", "bars_held"))
    ]
    assert numeric and all(
        h.endswith(("_pts", "_r", "_bars", "_prem", "_inr", "_pct")) for h in numeric
    )
    assert rows[0]["target_hit"] == "True" and rows[1]["stop_hit"] == "True"
    assert rows[0]["strike"] == "" and rows[0]["entry_time_ist"].endswith("+05:30")
    js = json.loads(to_json(ts, summ))
    assert len(js["trades"]) == 2 and js["analytics"]["n_trades"] == 2
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(to_xlsx(ts, summ)))
    assert wb["trades"].max_row == 3 and wb["analytics"].max_row == len(summ) + 1
