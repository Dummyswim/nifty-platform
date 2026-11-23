"""Trade-list exports (csv | xlsx | json). The unit is part of every numeric header."""

import csv
import io
import json
from collections.abc import Sequence
from typing import Any

from nifty.contracts import TradeRecord
from nifty.timeutil import to_ist

COLUMNS: list[tuple[str, str]] = [
    ("trade_id", "trade_id"),
    ("side", "side"),
    ("entry_time_ist", "entry_time"),
    ("exit_time_ist", "exit_time"),
    ("strike", "strike"),
    ("option_type", "option_type"),
    ("entry_px_pts", "entry_px"),
    ("exit_px_pts", "exit_px"),
    ("gross_pts", "gross_pts"),
    ("cost_pts", "cost_pts"),
    ("net_pts", "net_pts"),
    ("r_multiple_r", "r_multiple"),
    ("mae_pts", "mae_pts"),
    ("mfe_pts", "mfe_pts"),
    ("bars_held_bars", "bars_held"),
    ("exit_reason", "exit_reason"),
    ("stop_hit", "stop_hit"),
    ("target_hit", "target_hit"),
    ("entry_prem_prem", "entry_prem"),
    ("exit_prem_prem", "exit_prem"),
    ("pnl_inr", "pnl_inr"),
    ("roi_pct", "roi_pct"),
    ("execution_mode", "execution_mode"),
    ("qty", "qty"),
]
STOP_REASONS = {"SL", "BE_STOP", "STOP", "STOP_FIRST"}
TARGET_REASONS = {"TP", "TARGET", "TARGET_FIRST"}


def trade_row(t: TradeRecord) -> dict[str, Any]:
    """Flat dict keyed by the unit-suffixed headers. Index trades: strike/option fields are null."""
    d = t.model_dump()
    d["strike"], d["option_type"] = None, None  # C12 fills these for option paper trades
    d["stop_hit"] = t.exit_reason in STOP_REASONS
    d["target_hit"] = t.exit_reason in TARGET_REASONS
    d["entry_time"] = to_ist(t.entry_time).isoformat()
    d["exit_time"] = to_ist(t.exit_time).isoformat()
    return {head: d[key] for head, key in COLUMNS}


def to_csv(trades: Sequence[TradeRecord]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[h for h, _ in COLUMNS])
    w.writeheader()
    w.writerows(trade_row(t) for t in trades)
    return buf.getvalue()


def to_json(trades: Sequence[TradeRecord], analytics: dict[str, Any]) -> str:
    return json.dumps(
        {"analytics": analytics, "trades": [trade_row(t) for t in trades]},
        default=str, allow_nan=False,
    )  # fmt: skip


def to_xlsx(trades: Sequence[TradeRecord], analytics: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "trades"
    ws.append([h for h, _ in COLUMNS])
    for t in trades:
        ws.append(list(trade_row(t).values()))
    an = wb.create_sheet("analytics")
    an.append(["metric", "value"])
    for k, v in analytics.items():
        an.append([k, ", ".join(v) if isinstance(v, list) else v])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
