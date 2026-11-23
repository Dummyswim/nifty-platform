"""Nifty VWAP-spread scalper: RSI 60/40 + VWAP (from the reference image) with EMA trend,
VWAP *spread* distance/speed gates, cost-aware targets, BUY/SELL labels, backtest and live advisory.

Never places orders. Same causal engine drives backtest and live.

  fetch      download 1-minute candles to CSV (Yahoo for a quick test, Dhan for real/futures data)
  backtest   run the engine over a CSV, print a report, write trades CSV and an HTML chart with labels
  live       Dhan WebSocket feed -> BUY/SELL/EXIT labels in the terminal, JSONL log and auto-refreshing chart
  find-future  print the current-month Nifty future's Dhan security id

"spread" here = close - session VWAP, measured in ATR ("how far") and its change over the last few
bars ("how fast"). The index itself has no volume, so use the Nifty future for a true VWAP;
on the index the engine falls back to an equal-weight session average (TWAP) and says so.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import subprocess
import sys
import time as clock
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
EXCHANGE_CODE = {"IDX_I": 0, "NSE_EQ": 1, "NSE_FNO": 2}
INSTRUMENT = {"IDX_I": "INDEX", "NSE_FNO": "FUTIDX"}


@dataclass(frozen=True)
class Config:
    minutes: int = 5
    # trend / momentum (reference image: RSI > 60 long, RSI < 40 short, price vs VWAP)
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_len: int = 14
    atr_len: int = 14
    rsi_long: float = 60.0
    rsi_short: float = 40.0
    rsi_cross_bars: int = 3          # RSI must have been on the other side of the level within these bars
    # spread = close - VWAP, in ATR units
    min_dev_atr: float = 0.25        # far enough from VWAP to be a real move
    max_dev_atr: float = 1.6         # not so far that we are chasing
    speed_bars: int = 3
    min_speed_atr: float = 0.35      # spread must have widened this much (ATR) over speed_bars
    close_pos_min: float = 0.6       # long: close in top 40% of the bar (short: bottom 40%)
    chop_bars: int = 20
    max_vwap_flips: int = 3          # VWAP side changes in chop_bars; more means ping-pong chop
    # risk (stop = entry candle low/high as in the image, clamped by ATR)
    min_risk_atr: float = 0.7
    max_risk_atr: float = 1.8
    target_r: float = 1.5
    be_r: float = 1.0                # after +be_r, stop moves to entry + round-trip cost + be_offset_r
    be_offset_r: float = 0.05
    max_hold_bars: int = 15
    # signal exits
    exit_vwap_buffer_atr: float = 0.1
    ext_atr: float = 2.0             # stretched this far from VWAP and stalling -> take profit
    rsi_exit: float = 50.0           # long exits below, short exits above
    # costs, round trip, as bps of price (2.5 bps ~ 6 points at 25,000: futures STT + fees + slippage)
    cost_bps: float = 2.5
    min_target_cost_mult: float = 2.5
    # session / limits
    entry_start: time = time(9, 30)
    entry_end: time = time(14, 45)
    flat_time: time = time(15, 15)
    warmup_bars: int = 30
    min_session_bars: int = 5
    cooldown_bars: int = 2
    max_trades_day: int = 6
    max_daily_loss_r: float = 3.0


@dataclass(frozen=True)
class Bar:
    ts: datetime  # interval start, IST
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


def in_session(ts: datetime) -> bool:
    local = ts.astimezone(IST)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Session-aligned (09:15) buckets; out-of-session bars dropped; gaps are never filled."""
    out: list[Bar] = []
    key = None
    for b in sorted(bars, key=lambda x: x.ts):
        if not in_session(b.ts):
            continue
        start = datetime.combine(b.ts.date(), SESSION_OPEN, IST)
        bucket = start + timedelta(minutes=int((b.ts - start).total_seconds() // 60 // minutes) * minutes)
        if bucket == key:
            p = out[-1]
            out[-1] = Bar(bucket, p.o, max(p.h, b.h), min(p.l, b.l), b.c, p.v + b.v)
        else:
            key = bucket
            out.append(Bar(bucket, b.o, b.h, b.l, b.c, b.v))
    return out


# ---------------------------------------------------------------- indicators

class EMA:
    def __init__(self, n: int):
        self.k, self.value = 2 / (n + 1), None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value


class RSI:
    def __init__(self, n: int):
        self.n, self.prev, self.ag, self.al, self.seed, self.value = n, None, None, None, [], None

    def update(self, close: float) -> float | None:
        if self.prev is None:
            self.prev = close
            return None
        ch, self.prev = close - self.prev, close
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if self.ag is None:
            self.seed.append((g, l))
            if len(self.seed) < self.n:
                return None
            self.ag = sum(x[0] for x in self.seed) / self.n
            self.al = sum(x[1] for x in self.seed) / self.n
        else:
            self.ag = (self.ag * (self.n - 1) + g) / self.n
            self.al = (self.al * (self.n - 1) + l) / self.n
        if self.ag == 0 and self.al == 0:
            self.value = 50.0
        else:
            self.value = 100.0 if self.al == 0 else 100 - 100 / (1 + self.ag / self.al)
        return self.value


class ATR:
    def __init__(self, n: int):
        self.n, self.seed, self.value = n, [], None

    def update(self, h: float, l: float, prev_close: float | None) -> float | None:
        tr = h - l if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
        if self.value is None:
            self.seed.append(tr)
            if len(self.seed) == self.n:
                self.value = sum(self.seed) / self.n
        else:
            self.value = (self.value * (self.n - 1) + tr) / self.n
        return self.value


# ---------------------------------------------------------------- engine

class Engine:
    """Bar-by-bar, causal. Signals are made on a completed bar and filled at the NEXT bar's open.
    If a stop and a target are both inside one bar the stop is assumed to hit first."""

    def __init__(self, cfg: Config = Config()):
        self.cfg = cfg
        self.bars: list[Bar] = []
        self.rows: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []
        self.ema_f, self.ema_s = EMA(cfg.ema_fast), EMA(cfg.ema_slow)
        self.rsi, self.atr = RSI(cfg.rsi_len), ATR(cfg.atr_len)
        self.rsi_hist: deque[float] = deque(maxlen=cfg.rsi_cross_bars + 1)
        self.pos: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self.pending_exit: str | None = None
        self.since_exit = 10**6
        self.prev_close: float | None = None
        self.sess: date | None = None
        self._new_session(None)

    def _new_session(self, d: date | None) -> None:
        self.sess = d
        self.cum_pv = self.cum_v = self.cum_tp = 0.0
        self.n_sess = 0
        self.dev_hist: list[float | None] = []
        self.side_hist: deque[int] = deque(maxlen=self.cfg.chop_bars)
        self.trades_today, self.r_today = 0, 0.0
        self.prev_close = None
        self.pending = self.pending_exit = None

    # -- public
    def on_bar(self, bar: Bar, trade: bool = True) -> list[dict[str, Any]]:
        cfg, ev = self.cfg, []
        if self.bars and bar.ts <= self.bars[-1].ts:
            return ev
        if bar.ts.date() != self.sess:
            if self.pos:
                ev.append(self._close(self.bars[-1], self.bars[-1].c, "SESSION_END"))
            self._new_session(bar.ts.date())
        self.since_exit += 1
        if self.pending:
            ev += self._fill(bar)
        if self.pos:
            ev += self._manage(bar)

        f = self._features(bar)
        self.bars.append(bar)
        self.rows.append({"ts": bar.ts, "o": bar.o, "h": bar.h, "l": bar.l, "c": bar.c, **f})

        end = (bar.ts + timedelta(minutes=cfg.minutes)).time()
        if self.pos:
            ev += self._after_close(bar, f, end)
        elif trade and not self.pending:
            sig = self._signal(bar, f, end)
            if sig:
                ev.append(sig)
        self.prev_close = bar.c
        return ev

    # -- features
    def _features(self, bar: Bar) -> dict[str, Any]:
        cfg = self.cfg
        tp = (bar.h + bar.l + bar.c) / 3
        self.n_sess += 1
        self.cum_tp += tp
        if bar.v > 0:
            self.cum_pv += tp * bar.v
            self.cum_v += bar.v
        weighted = self.cum_v > 0
        vwap = self.cum_pv / self.cum_v if weighted else self.cum_tp / self.n_sess
        ef, es = self.ema_f.update(bar.c), self.ema_s.update(bar.c)
        rsi = self.rsi.update(bar.c)
        atr = self.atr.update(bar.h, bar.l, self.prev_close)
        if rsi is not None:
            self.rsi_hist.append(rsi)
        dev = bar.c - vwap
        dev_atr = dev / atr if atr else None
        self.dev_hist.append(dev_atr)
        speed = None
        if dev_atr is not None and len(self.dev_hist) > cfg.speed_bars:
            past = self.dev_hist[-1 - cfg.speed_bars]
            speed = None if past is None else dev_atr - past
        self.side_hist.append(1 if dev > 0 else -1 if dev < 0 else 0)
        sides = [s for s in self.side_hist if s]
        flips = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
        return {"vwap": vwap, "vwap_kind": "VWAP" if weighted else "TWAP", "ema_f": ef, "ema_s": es,
                "rsi": rsi, "atr": atr, "dev": dev, "dev_atr": dev_atr, "speed": speed, "flips": flips}

    # -- entries
    def _signal(self, bar: Bar, f: dict[str, Any], end: time) -> dict[str, Any] | None:
        c = self.cfg
        atr, rsi, d, s = f["atr"], f["rsi"], f["dev_atr"], f["speed"]
        if None in (atr, rsi, d, s) or len(self.bars) < c.warmup_bars or self.n_sess < c.min_session_bars:
            return None
        if not c.entry_start <= end <= c.entry_end or self.since_exit < c.cooldown_bars:
            return None
        if self.trades_today >= c.max_trades_day or self.r_today <= -c.max_daily_loss_r or f["flips"] > c.max_vwap_flips:
            return None
        rng = bar.h - bar.l
        loc = (bar.c - bar.l) / rng if rng > 0 else 0.5
        prev = list(self.rsi_hist)[:-1]
        long_ok = (bar.c > f["vwap"] and f["ema_f"] > f["ema_s"] and rsi >= c.rsi_long
                   and any(r < c.rsi_long for r in prev) and c.min_dev_atr <= d <= c.max_dev_atr
                   and s >= c.min_speed_atr and bar.c > bar.o and loc >= c.close_pos_min)
        short_ok = (bar.c < f["vwap"] and f["ema_f"] < f["ema_s"] and rsi <= c.rsi_short
                    and any(r > c.rsi_short for r in prev) and -c.max_dev_atr <= d <= -c.min_dev_atr
                    and s <= -c.min_speed_atr and bar.c < bar.o and loc <= 1 - c.close_pos_min)
        if not (long_ok or short_ok):
            return None
        sign = 1 if long_ok else -1
        raw = (bar.c - bar.l) if long_ok else (bar.h - bar.c)
        if raw > c.max_risk_atr * atr:
            return None
        risk = max(raw, c.min_risk_atr * atr)
        if c.target_r * risk < c.min_target_cost_mult * bar.c * c.cost_bps / 1e4:
            return None
        side = "BUY" if long_ok else "SELL"
        stop, target = bar.c - sign * risk, bar.c + sign * c.target_r * risk
        why = (f"RSI {rsi:.0f} crossed {c.rsi_long if long_ok else c.rsi_short:.0f} | {f['vwap_kind']} spread {d:+.2f} ATR "
               f"({f['dev']:+.1f} pts) | speed {s:+.2f} ATR/{c.speed_bars}bars | EMA{c.ema_fast}{'>' if long_ok else '<'}{c.ema_slow}")
        sig = {"type": "SIGNAL", "side": side, "ts": bar.ts, "ref": bar.c, "stop": stop, "target": target,
               "risk": risk, "atr": atr, "rsi": rsi, "dev_atr": d, "speed": s, "vwap": f["vwap"], "why": why,
               "text": f"{side} {bar.c:.1f} | SL {stop:.1f} | TP {target:.1f} | risk {risk:.1f} pts"}
        self.signals.append(sig)
        self.pending = sig
        return sig

    def _fill(self, bar: Bar) -> list[dict[str, Any]]:
        c, sig = self.cfg, self.pending
        self.pending = None
        sign = 1 if sig["side"] == "BUY" else -1
        risk = (bar.o - sig["stop"]) * sign
        if risk <= 0 or risk > c.max_risk_atr * sig["atr"] * 1.25 or c.target_r * risk < c.min_target_cost_mult * bar.o * c.cost_bps / 1e4:
            return [{"type": "SKIP", "side": sig["side"], "ts": bar.ts, "reason": f"gap at open {bar.o:.1f}"}]
        self.trades_today += 1
        self.pos = {"side": sig["side"], "sign": sign, "entry": bar.o, "stop": sig["stop"], "stop0": sig["stop"],
                    "target": bar.o + sign * c.target_r * risk, "risk": risk, "entry_ts": bar.ts, "bars": 0,
                    "mfe": 0.0, "mae": 0.0, "be": False, "why": sig["why"]}
        return [{"type": "ENTRY", "side": sig["side"], "ts": bar.ts, "price": bar.o, "stop": self.pos["stop"],
                 "target": self.pos["target"]}]

    # -- open position
    def _manage(self, bar: Bar) -> list[dict[str, Any]]:
        p, s = self.pos, self.pos["sign"]
        if self.pending_exit:
            reason, self.pending_exit = self.pending_exit, None
            return [self._close(bar, bar.o, reason)]
        if (bar.l <= p["stop"]) if s == 1 else (bar.h >= p["stop"]):
            gapped = (bar.o <= p["stop"]) if s == 1 else (bar.o >= p["stop"])
            return [self._close(bar, bar.o if gapped else p["stop"], "BE_STOP" if p["be"] else "SL")]
        if (bar.h >= p["target"]) if s == 1 else (bar.l <= p["target"]):
            gapped = (bar.o >= p["target"]) if s == 1 else (bar.o <= p["target"])
            return [self._close(bar, bar.o if gapped else p["target"], "TP")]
        favorable = (bar.h - p["entry"]) if s == 1 else (p["entry"] - bar.l)
        adverse = (p["entry"] - bar.l) if s == 1 else (bar.h - p["entry"])
        p["mfe"], p["mae"] = max(p["mfe"], favorable), max(p["mae"], adverse)
        return []

    def _after_close(self, bar: Bar, f: dict[str, Any], end: time) -> list[dict[str, Any]]:
        c, p = self.cfg, self.pos
        s = p["sign"]
        p["bars"] += 1
        if not p["be"] and p["mfe"] >= c.be_r * p["risk"]:
            p["be"] = True
            level = p["entry"] + s * (p["entry"] * c.cost_bps / 1e4 + c.be_offset_r * p["risk"])
            p["stop"] = max(p["stop"], level) if s == 1 else min(p["stop"], level)
        if end >= c.flat_time:
            return [self._close(bar, bar.c, "EOD")]
        reason = self._exit_reason(bar, f)
        if reason:
            self.pending_exit = reason
            return [{"type": "EXIT_SIGNAL", "side": p["side"], "ts": bar.ts, "price": bar.c, "reason": reason,
                     "text": f"EXIT {'LONG' if s == 1 else 'SHORT'} ({reason}) at {bar.c:.1f}"}]
        return []

    def _exit_reason(self, bar: Bar, f: dict[str, Any]) -> str | None:
        c, p = self.cfg, self.pos
        s, atr = p["sign"], f["atr"]
        if (bar.c - f["vwap"]) * s < -c.exit_vwap_buffer_atr * atr:
            return "VWAP_LOSS"
        if f["dev_atr"] * s >= c.ext_atr and (bar.c - self.prev_close) * s < 0:
            return "STRETCH_STALL"
        if f["rsi"] is not None and (f["rsi"] < c.rsi_exit if s == 1 else f["rsi"] > c.rsi_exit):
            return "RSI_FADE"
        if p["bars"] >= c.max_hold_bars:
            return "TIME"
        return None

    def _close(self, bar: Bar, price: float, reason: str) -> dict[str, Any]:
        p, c = self.pos, self.cfg
        gross = (price - p["entry"]) * p["sign"]
        cost = p["entry"] * c.cost_bps / 1e4
        net = gross - cost
        r = net / p["risk"]
        t = {"side": p["side"], "entry_ts": p["entry_ts"], "entry": p["entry"], "stop0": p["stop0"], "target": p["target"],
             "exit_ts": bar.ts, "exit": price, "reason": reason, "bars": p["bars"], "risk": p["risk"],
             "gross_pts": gross, "cost_pts": cost, "net_pts": net, "gross_r": gross / p["risk"], "r": r,
             "mfe_r": p["mfe"] / p["risk"], "mae_r": p["mae"] / p["risk"], "why": p["why"]}
        self.trades.append(t)
        self.r_today += r
        self.since_exit = 0
        self.pos = self.pending_exit = None
        return {"type": "EXIT", "side": t["side"], "ts": bar.ts, "price": price, "reason": reason,
                "net_pts": net, "r": r, "text": f"{reason} {price:.1f} ({r:+.2f}R, {net:+.1f} pts net)"}


# ---------------------------------------------------------------- data

def _parse_ts(value: str) -> datetime:
    value = value.strip()
    if value.replace(".", "", 1).isdigit():
        return datetime.fromtimestamp(float(value), IST)
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)


def read_csv(path: Path) -> list[Bar]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    bars = []
    for r in rows:
        try:
            bar = Bar(_parse_ts(r["timestamp"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                      float(r.get("volume") or 0))
        except (KeyError, ValueError):
            continue
        if all(math.isfinite(x) and x > 0 for x in (bar.o, bar.h, bar.l, bar.c)) and bar.l <= min(bar.o, bar.c) and bar.h >= max(bar.o, bar.c):
            bars.append(bar)
    return sorted({b.ts: b for b in bars}.values(), key=lambda b: b.ts)


def write_csv(bars: list[Bar], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.ts.isoformat(), b.o, b.h, b.l, b.c, b.v])


def _http(url: str, data: dict | None = None, headers: dict | None = None) -> Any:
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"HTTP {err.code} from {url.split('?')[0]}: {err.read()[:300].decode(errors='replace')}") from None


def fetch_yahoo(days: int, symbol: str = "^NSEI") -> list[Bar]:
    """Unofficial Yahoo endpoint: 1-minute bars, last ~30 days, index volume is always 0."""
    end, bars = datetime.now(timezone.utc), []
    for k in range(math.ceil(min(days, 29) / 7)):
        hi, lo = end - timedelta(days=7 * k), end - timedelta(days=7 * (k + 1))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('^', '%5E')}"
               f"?interval=1m&period1={int(lo.timestamp())}&period2={int(hi.timestamp())}")
        res = (_http(url).get("chart", {}).get("result") or [None])[0]
        if not res or "timestamp" not in res:
            continue
        q = res["indicators"]["quote"][0]
        for i, t in enumerate(res["timestamp"]):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                continue
            bars.append(Bar(datetime.fromtimestamp(t, IST), q["open"][i], q["high"][i], q["low"][i], q["close"][i],
                            float(q["volume"][i] or 0)))
    cutoff = datetime.now(IST) - timedelta(days=days)
    return sorted({b.ts: b for b in bars if b.ts >= cutoff}.values(), key=lambda b: b.ts)


def _dhan_headers() -> dict[str, str]:
    token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DHAN_ACCESS_TOKEN (and DHAN_CLIENT_ID) in your environment")
    return {"access-token": token, "client-id": os.getenv("DHAN_CLIENT_ID", "").strip(), "Content-Type": "application/json",
            "Accept": "application/json"}


def fetch_dhan(segment: str, security_id: str, start: datetime, end: datetime) -> list[Bar]:
    bars, cursor = [], start
    while cursor < end:
        stop = min(cursor + timedelta(days=60), end)
        body = {"securityId": str(security_id), "exchangeSegment": segment, "instrument": INSTRUMENT[segment],
                "interval": "1", "oi": False, "fromDate": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                "toDate": stop.strftime("%Y-%m-%d %H:%M:%S")}
        d = _http("https://api.dhan.co/v2/charts/intraday", body, _dhan_headers())
        for t, o, h, l, c, v in zip(d.get("timestamp", []), d.get("open", []), d.get("high", []), d.get("low", []),
                                    d.get("close", []), d.get("volume", [0] * len(d.get("timestamp", [])))):
            bars.append(Bar(datetime.fromtimestamp(t, IST), o, h, l, c, float(v or 0)))
        cursor = stop
    return sorted({b.ts: b for b in bars if in_session(b.ts)}.values(), key=lambda b: b.ts)


def find_nifty_future() -> dict[str, str]:
    req = urllib.request.Request("https://images.dhan.co/api-data/api-scrip-master.csv", headers={"User-Agent": "Mozilla/5.0"})
    today, best = datetime.now(IST).date(), None
    with urllib.request.urlopen(req, timeout=120) as resp:
        for row in csv.DictReader(line.decode("utf-8", "replace") for line in resp):
            if row["SEM_EXM_EXCH_ID"] == "NSE" and row["SEM_INSTRUMENT_NAME"] == "FUTIDX" and row["SEM_TRADING_SYMBOL"].startswith("NIFTY-"):
                expiry = datetime.fromisoformat(row["SEM_EXPIRY_DATE"]).date()
                if expiry >= today and (best is None or expiry < best[0]):
                    best = (expiry, row)
    if best is None:
        raise SystemExit("No NIFTY future found in the Dhan instrument master")
    return {"security_id": best[1]["SEM_SMST_SECURITY_ID"], "symbol": best[1]["SEM_TRADING_SYMBOL"],
            "expiry": str(best[0]), "lot": best[1]["SEM_LOT_UNITS"]}


# ---------------------------------------------------------------- report

def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if not n:
        return {"trades": 0}
    wins = [t for t in trades if t["net_pts"] > 0]
    loss = [t for t in trades if t["net_pts"] <= 0]
    gw, gl = sum(t["net_pts"] for t in wins), -sum(t["net_pts"] for t in loss)
    equity = peak = dd = streak = worst = 0.0
    for t in trades:
        equity += t["net_pts"]
        peak, dd = max(peak, equity), max(dd, peak - equity)
        streak = streak + 1 if t["net_pts"] <= 0 else 0
        worst = max(worst, streak)
    return {"trades": n, "win_rate": len(wins) / n, "net_pts": equity, "gross_pts": sum(t["gross_pts"] for t in trades),
            "cost_pts": sum(t["cost_pts"] for t in trades), "expectancy_r": sum(t["r"] for t in trades) / n,
            "gross_expectancy_r": sum(t["gross_r"] for t in trades) / n,
            "avg_win_r": sum(t["r"] for t in wins) / len(wins) if wins else 0.0,
            "avg_loss_r": sum(t["r"] for t in loss) / len(loss) if loss else 0.0,
            "profit_factor": gw / gl if gl else math.inf, "max_drawdown_pts": dd, "max_losing_streak": int(worst)}


def print_report(trades: list[dict[str, Any]], engine: Engine) -> None:
    s = summarize(trades)
    days = sorted({r["ts"].date() for r in engine.rows})
    print(f"\nBars {len(engine.rows)} over {len(days)} sessions ({days[0]} .. {days[-1]}) | timeframe {engine.cfg.minutes}m "
          f"| VWAP kind: {engine.rows[-1]['vwap_kind']}")
    if not s["trades"]:
        print("No trades generated.")
        return
    print(f"Trades {s['trades']} | win rate {s['win_rate']:.0%} | PF {s['profit_factor']:.2f} | max losing streak {s['max_losing_streak']}")
    print(f"Net {s['net_pts']:+.1f} pts (gross {s['gross_pts']:+.1f}, costs {-s['cost_pts']:.1f}) | max drawdown {s['max_drawdown_pts']:.1f} pts")
    print(f"Expectancy {s['expectancy_r']:+.3f} R net / {s['gross_expectancy_r']:+.3f} R gross | avg win {s['avg_win_r']:+.2f} R, avg loss {s['avg_loss_r']:+.2f} R")
    for label, key in (("side", "side"), ("exit", "reason")):
        groups: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            groups.setdefault(t[key], []).append(t)
        print("By " + label + ": " + " | ".join(f"{k} n={len(v)} {sum(x['net_pts'] for x in v):+.0f}pts" for k, v in sorted(groups.items())))
    daily: dict[date, float] = {}
    for t in trades:
        daily[t["entry_ts"].date()] = daily.get(t["entry_ts"].date(), 0.0) + t["net_pts"]
    print("By day: " + " | ".join(f"{d:%d-%b} {v:+.0f}" for d, v in sorted(daily.items())))
    print("Backtest is not a forecast: small samples, costs and fills are assumptions. Forward-test before risking money.")


def write_trades(trades: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = ["side", "entry_ts", "entry", "stop0", "target", "exit_ts", "exit", "reason", "bars", "risk", "gross_pts",
            "cost_pts", "net_pts", "r", "mfe_r", "mae_r", "why"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(keys)
        for t in trades:
            w.writerow([round(t[k], 3) if isinstance(t[k], float) else t[k] for k in keys])


def apply_overrides(cfg: Config, pairs: list[str]) -> Config:
    valid = {f.name for f in fields(cfg)}
    changes: dict[str, Any] = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if key not in valid or not raw:
            raise SystemExit(f"--set expects name=value; valid names: {', '.join(sorted(valid))}")
        cur = getattr(cfg, key)
        changes[key] = time.fromisoformat(raw) if isinstance(cur, time) else int(raw) if isinstance(cur, int) else float(raw)
    return replace(cfg, **changes)


def make_chart(engine: Engine, path: Path, **kw: Any) -> None:
    try:
        from scalper_chart import build_chart
    except ImportError as err:
        print(f"Chart skipped ({err}); pip install plotly", file=sys.stderr)
        return
    build_chart(engine, path, **kw)


# ---------------------------------------------------------------- live

GREEN, RED, DIM, BOLD, OFF = "\033[1;97;42m", "\033[1;97;41m", "\033[2m", "\033[1m", "\033[0m"


class LiveOutput:
    def __init__(self, jsonl: Path, chart: Path | None, notify: bool):
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        self.fh, self.chart, self.notify = jsonl.open("a", encoding="utf-8", buffering=1), chart, notify

    def handle(self, engine: Engine, bar: Bar, events: list[dict[str, Any]]) -> None:
        f, end = engine.rows[-1], bar.ts + timedelta(minutes=engine.cfg.minutes)
        bias = "BULL" if f["c"] > f["vwap"] and f["ema_f"] > f["ema_s"] else "BEAR" if f["c"] < f["vwap"] and f["ema_f"] < f["ema_s"] else "MIXED"
        if f["atr"] is not None and f["rsi"] is not None:
            speed = "n/a" if f["speed"] is None else f"{f['speed']:+.2f}"
            print(f"{DIM}{end:%H:%M} {bar.c:,.1f} | {f['vwap_kind']} {f['vwap']:,.1f} ({f['dev_atr']:+.2f} ATR) | RSI {f['rsi']:.0f} "
                  f"| speed {speed} | {bias}{OFF}", flush=True)
        else:
            print(f"{DIM}{end:%H:%M} {bar.c:,.1f} warming up ({len(engine.bars)}/{engine.cfg.warmup_bars} bars){OFF}", flush=True)
        for e in events:
            tag = e["type"]
            if tag == "SIGNAL":
                badge = GREEN if e["side"] == "BUY" else RED
                print(f"\a{badge} {e['side']} {OFF} {BOLD}{e['text']}{OFF}\n      {e['why']}", flush=True)
                self._notify(f"{e['side']} Nifty {e['ref']:.0f}  SL {e['stop']:.0f}  TP {e['target']:.0f}")
            elif tag == "EXIT_SIGNAL":
                print(f"\a{BOLD}  >> {e['text']} - square off now{OFF}", flush=True)
                self._notify(e["text"])
            elif tag in ("ENTRY", "EXIT", "SKIP"):
                print(f"{DIM}  paper {tag.lower()}: {e.get('text') or e.get('reason') or e.get('price')}{OFF}", flush=True)
            self.fh.write(json.dumps({**e, "ts": e["ts"].isoformat()}, default=str) + "\n")
        if self.chart is not None:
            make_chart(engine, self.chart, live=True)

    def _notify(self, msg: str) -> None:
        if self.notify and sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Nifty scalper"'], check=False)


async def run_live(engine: Engine, out: LiveOutput, args: argparse.Namespace) -> None:
    try:
        import websockets
        from nifty_assistant import CandleBuilder, FeedDisconnect, decode_message
    except ImportError as err:
        raise SystemExit(f"Live mode needs websockets and nifty_assistant.py in the same folder: {err}") from None
    token, client = os.getenv("DHAN_ACCESS_TOKEN", "").strip(), os.getenv("DHAN_CLIENT_ID", "").strip()
    if not token or not client:
        raise SystemExit("Set DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID in your environment")
    url = f"wss://api-feed.dhan.co?version=2&token={token}&clientId={client}&authType=2"
    sub = {"RequestCode": 17, "InstrumentCount": 1, "InstrumentList": [{"ExchangeSegment": args.segment, "SecurityId": str(args.security_id)}]}

    minutes = engine.cfg.minutes

    def backfill(bar: Bar) -> None:
        """Fill buckets the live builder cannot provide (its first partial candle, reconnect holes) from Dhan REST."""
        if args.no_seed:
            return
        last = engine.bars[-1].ts if engine.bars and engine.bars[-1].ts.date() == bar.ts.date() else None
        start = last + timedelta(minutes=minutes) if last else datetime.combine(bar.ts.date(), SESSION_OPEN, IST)
        if start >= bar.ts:
            return
        try:
            for b in resample(fetch_dhan(args.segment, args.security_id, start, bar.ts), minutes):
                if b.ts < bar.ts:
                    engine.on_bar(b, trade=False)
            print(f"{DIM}backfilled {start:%H:%M}-{bar.ts:%H:%M} from Dhan history{OFF}", flush=True)
        except (SystemExit, OSError, ValueError, KeyError) as err:
            print(f"Backfill failed ({err}); indicators continue with a gap", file=sys.stderr)

    def publish(c: Any) -> None:
        bar = Bar(c.timestamp.astimezone(IST), c.open, c.high, c.low, c.close, float(c.volume or 0))
        backfill(bar)
        events = engine.on_bar(bar)
        if events or engine.rows[-1]["ts"] == bar.ts:
            out.handle(engine, bar, events)

    failures = 0
    while True:
        builder = CandleBuilder(minutes, index_feed=args.segment == "IDX_I")
        last_tick = clock.monotonic()
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=20, close_timeout=5,
                                          max_size=1 << 20, compression=None) as ws:
                await ws.send(json.dumps(sub))
                print(f"Connected: {args.segment}:{args.security_id} - waiting for live ticks (first partial candle is skipped)", flush=True)
                while True:
                    now = datetime.now(timezone.utc)
                    for c in builder.flush(now):
                        publish(c)
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    except asyncio.TimeoutError:
                        if in_session(now) and clock.monotonic() - last_tick > args.stale_seconds:
                            raise TimeoutError("no fresh ticks") from None
                        continue
                    if not isinstance(msg, bytes):
                        raise FeedDisconnect(f"unexpected text from Dhan: {str(msg)[:120]}")
                    for tick in decode_message(msg, int(args.security_id), EXCHANGE_CODE[args.segment]):
                        if in_session(tick.timestamp):
                            last_tick, failures = clock.monotonic(), 0
                            for c in builder.push(tick):
                                publish(c)
        except FeedDisconnect:
            raise
        except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException) as err:
            failures += 1
            if args.max_reconnects and failures > args.max_reconnects:
                raise SystemExit("Reconnect limit reached") from None
            delay = min(60, 2 ** min(failures, 6))
            print(f"Feed interrupted ({type(err).__name__}: {err}); reconnecting in {delay}s - bars may be missing", file=sys.stderr)
            await asyncio.sleep(delay)


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--minutes", type=int, default=Config.minutes, help="signal timeframe (default %(default)s)")
        p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="override any Config field, e.g. --set target_r=2")

    f = sub.add_parser("fetch", help="download 1-minute candles to CSV")
    f.add_argument("--source", choices=["yahoo", "dhan"], default="yahoo")
    f.add_argument("--days", type=int, default=25)
    f.add_argument("--segment", choices=list(INSTRUMENT), default="IDX_I")
    f.add_argument("--security-id", default="13")
    f.add_argument("--out", type=Path, default=Path("data/nifty_1m.csv"))

    b = sub.add_parser("backtest", help="run the engine over a 1-minute CSV")
    b.add_argument("--csv", type=Path, required=True)
    b.add_argument("--trades", type=Path, default=Path("logs/scalper_trades.csv"))
    b.add_argument("--chart", type=Path, default=Path("logs/scalper_chart.html"))
    b.add_argument("--no-chart", action="store_true")
    b.add_argument("--last-days", type=int, default=0, help="chart only the last N sessions (0 = all)")
    common(b)

    lv = sub.add_parser("live", help="live advisory labels from the Dhan feed")
    lv.add_argument("--segment", choices=list(EXCHANGE_CODE), default="IDX_I")
    lv.add_argument("--security-id", default="13")
    lv.add_argument("--jsonl", type=Path, default=Path("logs/scalper_live.jsonl"))
    lv.add_argument("--chart", type=Path, default=Path("logs/scalper_live.html"))
    lv.add_argument("--no-chart", action="store_true")
    lv.add_argument("--notify", action="store_true", help="macOS notification on BUY/SELL/EXIT")
    lv.add_argument("--no-seed", action="store_true", help="skip Dhan historical warmup/backfill (VWAP then starts at connect time)")
    lv.add_argument("--stale-seconds", type=float, default=20)
    lv.add_argument("--max-reconnects", type=int, default=0)
    common(lv)

    sub.add_parser("find-future", help="print current-month Nifty future's Dhan security id")
    args = ap.parse_args(argv)

    if args.cmd == "find-future":
        print(json.dumps(find_nifty_future(), indent=2))
        return
    if args.cmd == "fetch":
        end = datetime.now(IST)
        bars = fetch_yahoo(args.days) if args.source == "yahoo" else fetch_dhan(args.segment, args.security_id, end - timedelta(days=args.days), end)
        write_csv(bars, args.out)
        print(f"Wrote {len(bars)} 1-minute bars to {args.out}" + (" (index volume is 0: VWAP will be a TWAP)" if bars and not any(x.v for x in bars) else ""))
        return

    cfg = apply_overrides(replace(Config(), minutes=args.minutes), args.set)
    engine = Engine(cfg)
    if args.cmd == "backtest":
        for bar in resample(read_csv(args.csv), cfg.minutes):
            engine.on_bar(bar)
        if not engine.rows:
            raise SystemExit("No in-session bars found in CSV")
        print_report(engine.trades, engine)
        write_trades(engine.trades, args.trades)
        print(f"Trades: {args.trades}")
        if not args.no_chart:
            make_chart(engine, args.chart, last_days=args.last_days)
            print(f"Chart: {args.chart}")
        return

    now = datetime.now(IST)
    if not args.no_seed:
        seed = resample(fetch_dhan(args.segment, args.security_id, now - timedelta(days=6), now), cfg.minutes)
        for bar in seed:
            if bar.ts + timedelta(minutes=cfg.minutes) <= now:
                engine.on_bar(bar, trade=False)
        print(f"Seeded {len(engine.bars)} bars of history (no alerts from history)")
    out = LiveOutput(args.jsonl, None if args.no_chart else args.chart, args.notify)
    try:
        asyncio.run(run_live(engine, out, args))
    except KeyboardInterrupt:
        print("Stopped. Paper positions are not persisted.")


if __name__ == "__main__":
    main()
