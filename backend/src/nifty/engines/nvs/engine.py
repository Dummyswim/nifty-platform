"""Engine `pine.nvs_scalper`: port of reference/pine/Nifty_VWAP_Spread_Scalper.pine (L29-358).

Per bar (docs/pine/NVS.md): broker fills first, then the script runs at the bar close. Variable
names follow the Pine source so the two can be read side by side.
"""

import math
from typing import Any

import nifty.engines.pinekit as pk
from nifty.contracts import Bar, EngineOutput, Ev, OverlayElement, PlotSpec, TradeRecord
from nifty.engines.base import register_engine
from nifty.engines.context import EngineContext
from nifty.engines.nvs.params import NvsParams
from nifty.execution.broker import BrokerEmulator

NaN = pk.NaN
SESSION_OPEN_MIN, SESSION_CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30


def to_min(hm: int) -> int:
    return hm // 100 * 60 + hm % 100


def _r1(x: float, nd: int) -> float:
    return math.floor(x * 10.0**nd + 0.5) / 10.0**nd


def _g(x: float) -> str:
    return f"{x:g}"


# scalar fields persisted by snapshot: name -> default
_SCALARS: dict[str, Any] = {
    "dir": 0, "wait_fill": False, "cur_stop": NaN, "cur_tp": NaN, "cur_risk": NaN,
    "be_on": False, "mfe": 0.0, "hold_bars": 0, "trades_today": 0, "r_today": 0.0,
    "since_exit": 1000, "prev_side": 0, "cum_pv": 0.0, "cum_v": 0.0, "cum_tp": 0.0,
    "n_sess": 0, "n_bars": 0, "prev_close": NaN, "prev_session": None,
    "sig_atr": NaN, "sig_start": None, "init_stop": NaN, "init_tp": NaN,
    "loss_tag": "SL", "sig_why": "",
}  # fmt: skip


class NvsScalper:
    id = "pine.nvs_scalper"
    version = "1"
    default_timeframe = "5m"
    Params = NvsParams
    plots = [
        PlotSpec(name="vwap", role="vwap", pane="overlay"),
        PlotSpec(name="ema_fast", pane="overlay"),
        PlotSpec(name="ema_slow", pane="overlay"),
        PlotSpec(name="buy_near", role="buy", pane="overlay"),
        PlotSpec(name="buy_far", role="buy", pane="overlay"),
        PlotSpec(name="sell_near", role="sell", pane="overlay"),
        PlotSpec(name="sell_far", role="sell", pane="overlay"),
        PlotSpec(name="stop", kind="step", role="sell", pane="overlay"),
        PlotSpec(name="target", kind="step", role="buy", pane="overlay"),
    ]
    warmup_bars = 30

    # script state (names follow the Pine `var`s); defaults in _SCALARS
    dir: int
    wait_fill: bool
    cur_stop: float
    cur_tp: float
    cur_risk: float
    be_on: bool
    mfe: float
    hold_bars: int
    trades_today: int
    r_today: float
    since_exit: int
    prev_side: int
    cum_pv: float
    cum_v: float
    cum_tp: float
    n_sess: int
    n_bars: int
    prev_close: float
    prev_session: str | None
    sig_atr: float
    sig_start: str | None
    init_stop: float
    init_tp: float
    loss_tag: str
    sig_why: str

    def __init__(self, params: NvsParams, ctx: EngineContext) -> None:
        self.p, self.ctx = params, ctx
        self.ema_f = pk.Ema(params.ema_fast_len, params.ema_seed)
        self.ema_s = pk.Ema(params.ema_slow_len, params.ema_seed)
        self.rsi_ind = pk.Rsi(params.rsi_len)
        self.atr_ind = pk.AtrSess(params.atr_len)
        self.rsi_h = pk.Series(params.rsi_cross_bars)  # rsi[1..N] (pushed after use)
        self.dev_h = pk.Series(params.speed_bars)  # devAtr[1..speed_bars]
        self.flip_h = pk.Series(max(params.chop_bars, 2))
        self.broker = BrokerEmulator(
            self.id, ctx.instrument.instrument_id, 1.0, params.commission_pct
        )
        self.deferred_r: list[float] = []  # R of trades closed `immediately`: visible next bar
        for k, v in _SCALARS.items():
            setattr(self, k, v)
        self.entry_start = to_min(params.entry_start_hm)
        self.entry_end = to_min(params.entry_end_hm)
        self.flat = to_min(params.flat_hm)
        self.last: dict[str, Any] = {}

    # ---- helpers ----------------------------------------------------------------------------
    def _risk_r(self, ep: float, xp: float, sgn: int) -> float:
        net = (xp - ep) * sgn - ep * self.p.cost_bps / 1e4
        return net / self.cur_risk if self.cur_risk > 0 else 0.0

    def _finish(self, t: TradeRecord, reason: str, bar: Bar, out: EngineOutput, now: bool) -> None:
        """Account a closed trade: tag, script-math R, event, overlays. `now`: R counts now."""
        sgn = 1 if t.side == "long" else -1
        r = self._risk_r(t.entry_px, t.exit_px, sgn)
        t = t.model_copy(update={"exit_reason": reason, "r_multiple": r})
        out.trades.append(t)
        out.events.append(
            Ev(
                "exit",
                {"side": t.side, "reason": reason, "r": r, "price": t.exit_px,
                 "entry_px": t.entry_px, "net_pts": t.net_pts, "flags": t.flags},
                "close" if t.exit_time == bar.bar_end_utc else "open",
            )
        )  # fmt: skip
        sig = t.signal_bar_start or t.entry_time
        base = f"nvs:{sig.isoformat()}"
        role = "buy" if t.side == "long" else "sell"
        out.overlay_ops += [
            OverlayElement(id=f"{base}:stop", kind="line", t0=sig, t1=t.exit_time,
                           p0=self.init_stop, p1=self.init_stop, style={"role": "sell"}),
            OverlayElement(id=f"{base}:target", kind="line", t0=sig, t1=t.exit_time,
                           p0=self.init_tp, p1=self.init_tp, style={"role": "buy"}),
            OverlayElement(id=f"{base}:exit", kind="marker", t0=t.exit_time, p0=t.exit_px,
                           text=f"{reason} {_r1(r, 1):g}R", style={"role": role}),
        ]  # fmt: skip
        if now:
            self._count(r)
        else:
            self.deferred_r.append(r)

    def _count(self, r: float) -> None:
        self.r_today += r
        self.since_exit = 0

    # ---- per bar ------------------------------------------------------------------------------
    def _step(self, bar: Bar) -> EngineOutput:
        p, out = self.p, EngineOutput()
        cal, mintick = self.ctx.calendar, self.ctx.mintick
        dir_start = self.dir
        # 1. clock
        start_min = pk.bar_minutes_ist(bar.bar_start_utc)
        in_sess = SESSION_OPEN_MIN <= start_min < SESSION_CLOSE_MIN
        end_min = pk.bar_minutes_ist(bar.bar_end_utc)
        sdate = cal.session_date(bar.bar_start_utc).isoformat()
        new_sess = in_sess and (self.prev_session is None or sdate != self.prev_session)
        self.prev_session = sdate
        self.n_bars += 1

        # fill_price anchor: re-anchor the bracket to the actual fill open, or decline (twin)
        declined = False
        if self.wait_fill and p.anchor_mode == "fill_price":
            sgn = self.dir
            risk = (bar.open - self.cur_stop) * sgn
            if (
                risk <= 0
                or risk > p.max_risk_atr * self.sig_atr * 1.25
                or p.target_r * risk < p.min_tgt_cost_x * bar.open * p.cost_bps / 1e4
            ):
                self.broker.cancel_entries()
                declined = True
            else:
                self.cur_risk = risk
                self.cur_tp = pk.round_to_mintick(bar.open + sgn * p.target_r * risk, mintick)
                self.init_tp = self.cur_tp
                self.broker.exit(stop=self.cur_stop, limit=self.cur_tp)

        closed = self.broker.on_bar(bar)
        if self.wait_fill:  # the entry filled at this bar's open (maybe stopped inside the bar)
            ap = self.broker.actual_position
            px = (
                ap.entry_px
                if ap is not None
                else next((t.entry_px for t in closed if t.entry_time == bar.bar_start_utc), NaN)
            )
            if px == px:
                eside = "long" if self.dir == 1 else "short"
                out.events.append(
                    Ev(
                        "entry",
                        {"side": eside, "price": px, "signal_bar_start": self.sig_start},
                        "open",
                    )
                )
                out.overlay_ops.append(
                    OverlayElement(id=f"nvs:{self.sig_start}:entry", kind="marker",
                                   t0=bar.bar_start_utc, p0=px,
                                   style={"role": "buy" if self.dir == 1 else "sell"})
                )  # fmt: skip

        # 2. indicators
        atr = self.atr_ind.update(bar.high, bar.low, bar.close, new_sess)
        rsi = self.rsi_ind.update(bar.close)
        ema_f, ema_s = self.ema_f.update(bar.close), self.ema_s.update(bar.close)
        if new_sess:
            self.cum_pv = self.cum_v = self.cum_tp = 0.0
            self.n_sess = 0
            self.prev_side = 0
        hlc3 = (bar.high + bar.low + bar.close) / 3
        if in_sess:
            v = 0.0 if bar.volume_kind == "absent" else pk.nz(bar.volume)
            self.n_sess += 1
            self.cum_tp += hlc3
            if v > 0:
                self.cum_pv += hlc3 * v
                self.cum_v += v
        weighted = self.cum_v > 0
        vwap = self.cum_pv / self.cum_v if weighted else self.cum_tp / max(self.n_sess, 1)

        # 3. spread
        dev = bar.close - vwap
        dev_atr = dev / atr if atr == atr and atr != 0 else NaN
        speed = dev_atr - self.dev_h[p.speed_bars - 1] if self.n_sess > p.speed_bars else NaN
        side = 1 if dev > 0 else -1 if dev < 0 else 0
        flip_at = (
            1.0
            if (in_sess and side != 0 and self.prev_side != 0 and side != self.prev_side)
            else 0.0
        )
        if in_sess and side != 0:
            self.prev_side = side
        self.flip_h.push(flip_at)
        flips = int(
            sum(
                pk.nz(self.flip_h[i])
                for i in range(0, max(0, min(p.chop_bars - 2, self.n_sess - 1)) + 1)
            )
        )
        rsi_was_below = any(self.rsi_h[i - 1] < p.rsi_long for i in range(1, p.rsi_cross_bars + 1))
        rsi_was_above = any(self.rsi_h[i - 1] > p.rsi_short for i in range(1, p.rsi_cross_bars + 1))
        rng = bar.high - bar.low
        loc = (bar.close - bar.low) / rng if rng > 0 else 0.5

        # 4. closed-trade accounting (emulator closes during this bar + `immediately` closes of t-1)
        self.since_exit = min(self.since_exit + 1, 1000)
        for r in self.deferred_r:
            self._count(r)
        self.deferred_r = []
        for t in closed:
            self._finish(t, self._map_reason(t), bar, out, now=True)
        # 5. new session
        if new_sess:
            self.trades_today, self.r_today = 0, 0.0

        # 6. bookkeeping
        pos = self.broker.position
        in_pos = pos is not None
        entry_px = self.broker.actual_position.entry_px if self.broker.actual_position else NaN
        if self.wait_fill:
            self.wait_fill = False
            if in_pos:
                self.hold_bars, self.mfe, self.be_on = 0, 0.0, False
            else:
                self.dir = 0
                if declined:
                    self.trades_today -= 1
        elif not in_pos:
            self.dir = 0
        if new_sess and in_pos:
            tr = self.broker.close_all("SESSION_END", immediately=True)
            if tr is not None:
                self._finish(tr, "SESSION_END", bar, out, now=False)

        # 7. exits
        exit_reason = ""
        if in_pos and self.dir != 0:
            d = self.dir
            self.hold_bars += 1
            self.mfe = max(self.mfe, bar.high - entry_px if d == 1 else entry_px - bar.low)
            if not self.be_on and self.mfe >= p.be_r * self.cur_risk:
                self.be_on = True
                lvl = entry_px + d * (entry_px * p.cost_bps / 1e4 + p.be_offset_r * self.cur_risk)
                self.cur_stop = max(self.cur_stop, lvl) if d == 1 else min(self.cur_stop, lvl)
                out.events.append(Ev("stop_update", {"stop": self.cur_stop, "reason": "BE"}))
            if end_min >= self.flat or pk.is_last_bar_of_session(bar, cal):
                exit_reason = "EOD"
            elif (bar.close - vwap) * d < -p.exit_vwap_buf_atr * atr:
                exit_reason = "VWAP_LOSS"
            elif dev_atr * d >= p.ext_atr and (bar.close - self.prev_close) * d < 0:
                exit_reason = "STRETCH_STALL"
            elif p.use_rsi and ((d == 1 and rsi < p.rsi_exit) or (d == -1 and rsi > p.rsi_exit)):
                exit_reason = "RSI_FADE"
            elif self.hold_bars >= p.max_hold_bars:
                exit_reason = "TIME"
            if exit_reason:
                if exit_reason == "EOD":
                    tr = self.broker.close(exit_reason, immediately=True)
                    if tr is not None:
                        self._finish(tr, "EOD", bar, out, now=False)
                    self.dir = 0
                else:
                    self.broker.close(exit_reason)
            else:
                self.loss_tag = "BE_STOP" if self.be_on else "SL"
                self.broker.exit(stop=self.cur_stop, limit=self.cur_tp)

        # 8. entry
        use_rsi = p.use_rsi
        ready = (
            in_sess and not self.ctx.provisional and atr == atr and (not use_rsi or rsi == rsi)
            and dev_atr == dev_atr and speed == speed
            and self.n_bars >= p.warmup_bars and self.n_sess >= p.min_sess_bars
            and self.entry_start <= end_min <= self.entry_end
            and self.since_exit >= p.cooldown_bars and self.trades_today < p.max_trades_day
            and self.r_today > -p.max_day_loss_r and flips <= p.max_vwap_flips
        )  # fmt: skip
        long_ok = (
            bar.close > vwap and ema_f > ema_s
            and (not use_rsi or (rsi >= p.rsi_long and rsi_was_below))
            and p.min_dev_atr <= dev_atr <= p.max_dev_atr and speed >= p.min_speed_atr
            and bar.close > bar.open and loc >= p.close_pos_min
        )  # fmt: skip
        short_ok = (
            bar.close < vwap and ema_f < ema_s
            and (not use_rsi or (rsi <= p.rsi_short and rsi_was_above))
            and -p.max_dev_atr <= dev_atr <= -p.min_dev_atr and speed <= -p.min_speed_atr
            and bar.close < bar.open and loc <= 1 - p.close_pos_min
        )  # fmt: skip
        sig_dir = 0
        if ready and not in_pos and not self.wait_fill and self.dir == 0:
            sig_dir = 1 if (long_ok and p.allow_long) else -1 if (short_ok and p.allow_short) else 0
        if sig_dir != 0:
            raw_risk = bar.close - bar.low if sig_dir == 1 else bar.high - bar.close
            risk = max(raw_risk, p.min_risk_atr * atr)
            if (
                raw_risk <= p.max_risk_atr * atr
                and p.target_r * risk >= p.min_tgt_cost_x * bar.close * p.cost_bps / 1e4
            ):
                self.dir, self.wait_fill, self.cur_risk = sig_dir, True, risk
                self.cur_stop = pk.round_to_mintick(bar.close - sig_dir * risk, mintick)
                self.cur_tp = pk.round_to_mintick(bar.close + sig_dir * p.target_r * risk, mintick)
                self.init_stop, self.init_tp, self.sig_atr = self.cur_stop, self.cur_tp, atr
                self.trades_today += 1
                self.loss_tag = "SL"
                self.sig_start = bar.bar_start_utc.isoformat()
                txt = "BUY" if sig_dir == 1 else "SELL"
                rsi_why = (
                    f"RSI {int(_r1(rsi, 0))} crossed "
                    f"{_g(p.rsi_long if sig_dir == 1 else p.rsi_short)}"
                    if use_rsi
                    else "RSI OFF"
                )
                why = (
                    f"{rsi_why} | {'VWAP' if weighted else 'TWAP'} "
                    f"spread {_r1(dev_atr, 2):.2f} ATR ({_r1(dev, 1):.1f} pts) | "
                    f"speed {_r1(speed, 2):.2f} ATR/{p.speed_bars} bars | "
                    f"EMA{p.ema_fast_len}{'>' if sig_dir == 1 else '<'}{p.ema_slow_len}"
                )
                self.broker.entry("long" if sig_dir == 1 else "short", bar.bar_start_utc, txt)
                self.broker.exit(stop=self.cur_stop, limit=self.cur_tp)
                out.events.append(
                    Ev("signal", {"side": txt, "close": bar.close, "stop": self.cur_stop,
                                  "target": self.cur_tp, "risk_pts": risk, "why": why}, "close")
                )  # fmt: skip
                out.overlay_ops.append(
                    OverlayElement(id=f"nvs:{self.sig_start}:signal", kind="marker",
                                   t0=bar.bar_start_utc, p0=bar.low if sig_dir == 1 else bar.high,
                                   text=f"{txt} {_r1(bar.close, 2):g}",
                                   style={"role": "buy" if sig_dir == 1 else "sell"})
                )  # fmt: skip

        # outputs
        zone = atr if in_sess else NaN
        lvl_on = dir_start != 0 or self.dir != 0
        out.plots = {
            "vwap": vwap if in_sess else NaN,
            "ema_fast": ema_f,
            "ema_slow": ema_s,
            "buy_near": vwap + p.min_dev_atr * zone,
            "buy_far": vwap + p.max_dev_atr * zone,
            "sell_near": vwap - p.min_dev_atr * zone,
            "sell_far": vwap - p.max_dev_atr * zone,
            "stop": self.cur_stop if lvl_on else NaN,
            "target": self.cur_tp if lvl_on else NaN,
        }
        # history pushed last: [i] above meant "i bars before this bar"
        self.rsi_h.push(rsi)
        self.dev_h.push(dev_atr)
        self.prev_close = bar.close
        self.last = {"weighted": weighted, "dev_atr": dev_atr, "dev": dev, "speed": speed,
                     "rsi": rsi, "close": bar.close, "vwap": vwap, "ema_f": ema_f,
                     "ema_s": ema_s, "flips": flips}  # fmt: skip
        return out

    def _map_reason(self, t: TradeRecord) -> str:
        if t.exit_reason == "TARGET":
            return "TP"
        if t.exit_reason == "STOP":
            return self.loss_tag
        return t.exit_reason

    # ---- Engine protocol ---------------------------------------------------------------------
    def on_bar(self, bar: Bar) -> EngineOutput:
        return self._step(bar)

    def on_provisional(self, bar: Bar) -> EngineOutput:
        tmp = NvsScalper(self.p, self.ctx)
        tmp.restore(self.snapshot())
        out = tmp._step(bar)
        return EngineOutput(plots=out.plots, events=out.events)

    def snapshot(self) -> dict[str, Any]:
        sc = {}
        for k in _SCALARS:
            v = getattr(self, k)
            sc[k] = pk.enc([v])[0] if isinstance(v, float) else v
        return {
            "sc": sc,
            "ema_f": self.ema_f.state(), "ema_s": self.ema_s.state(),
            "rsi": self.rsi_ind.state(), "atr": self.atr_ind.state(),
            "rsi_h": self.rsi_h.state(), "dev_h": self.dev_h.state(),
            "flip_h": self.flip_h.state(), "broker": self.broker.state(),
            "deferred_r": list(self.deferred_r),
        }  # fmt: skip

    def restore(self, snap: dict[str, Any]) -> None:
        for k, v in snap["sc"].items():
            setattr(
                self, k, pk.dec([v])[0] if (v is None and isinstance(_SCALARS[k], float)) else v
            )
        self.ema_f.load(snap["ema_f"])
        self.ema_s.load(snap["ema_s"])
        self.rsi_ind.load(snap["rsi"])
        self.atr_ind.load(snap["atr"])
        self.rsi_h.load(snap["rsi_h"])
        self.dev_h.load(snap["dev_h"])
        self.flip_h.load(snap["flip_h"])
        self.broker.load(snap["broker"])
        self.deferred_r = list(snap["deferred_r"])

    def panel(self) -> dict[str, Any] | None:
        lt = self.last
        if not lt:
            return None
        p = self.p

        def f(x: float, nd: int) -> str:
            return "n/a" if x != x else f"{_r1(x, nd):.{nd}f}"

        bull = lt["close"] > lt["vwap"] and lt["ema_f"] > lt["ema_s"]
        bear = lt["close"] < lt["vwap"] and lt["ema_f"] < lt["ema_s"]
        bias = "BULL" if bull else "BEAR" if bear else "MIXED"
        pos = "LONG" if self.dir == 1 else "SHORT" if self.dir == -1 else "FLAT"
        spd = "n/a" if lt["speed"] != lt["speed"] else f"{f(lt['speed'], 2)} ATR"
        chop = "  CHOP" if lt["flips"] > p.max_vwap_flips else ""
        rows = [
            ("NVS Scalper 5m", "VWAP" if lt["weighted"] else "TWAP", "neutral"),
            ("Spread", f"{f(lt['dev_atr'], 2)} ATR ({f(lt['dev'], 1)} pts)", "neutral"),
            (f"Speed ({p.speed_bars} bars)", spd, "neutral"),
            ("RSI (ON)" if p.use_rsi else "RSI (OFF)", f(lt["rsi"], 1), "neutral"),
            ("Bias", bias, "buy" if bull else "sell" if bear else "neutral"),
            ("VWAP flips", f"{lt['flips']} / {p.max_vwap_flips}{chop}", "neutral"),
            ("Today", f"{self.trades_today} trades, {_r1(self.r_today, 1):g}R", "neutral"),
            ("Position", pos, "buy" if self.dir == 1 else "sell" if self.dir == -1 else "neutral"),
        ]  # fmt: skip
        return {"rows": [{"label": a, "value": b, "role": c} for a, b, c in rows]}


register_engine(NvsScalper, ready=True)
