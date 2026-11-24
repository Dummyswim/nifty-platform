"""Step 13 (L770-846): path history, descriptive statistics only (not a forecast, D18).

27 buckets `stateId = regimeIdx*9 + (flowState+1)*3 + locIdx`. One global episode at a time. The
rules run in Pine's order on every confirmed bar; a hit on bar H beats the timeout at H; a session
boundary censors an unfinished episode (`sessionCut`)."""

from dataclasses import dataclass
from typing import Any

from nifty.contracts import PlotSpec
from nifty.engines.balu.params import BaluParams, session_minutes
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, register_slot, step
from nifty.engines.pinekit import bar_minutes_ist, is_last_bar_of_session

N = 27
PLOT_SPECS += [
    PlotSpec(name=n, pane="own")
    for n in (
        "state_id",
        "n_up",
        "n_dn",
        "n_timeout",
        "n_both",
        "n_cut",
        "n_pending",
        "sample_days",
    )
]


def state_id(regime_idx: int, flow_state: int, loc_idx: int) -> int:
    return regime_idx * 9 + (flow_state + 1) * 3 + loc_idx


@dataclass
class Stats:
    n_up: int
    n_dn: int
    n_timeout: int
    n_both: int
    n_cut: int
    n_pending: int
    sample_days: int
    n_resolved: int
    n_finished: int
    resolved_share: float | None  # 100 * up / resolved
    history_lo: float | None  # 100 * up / finished
    history_hi: float | None  # 100 * (up + both + cut) / finished
    prob_ready: bool


class PathHistory:
    def __init__(self) -> None:
        self.hit_up = [0] * N
        self.hit_dn = [0] * N
        self.timed_out = [0] * N
        self.both_hit = [0] * N
        self.session_cut = [0] * N
        self.sample_days = [0] * N
        self.last_sample_day: list[str | None] = [None] * N
        self.prev_state: int | None = None
        self.p_state: int | None = None  # open episode: bucket, barriers, start bar
        self.p_up = float("nan")
        self.p_dn = float("nan")
        self.p_bar = 0

    # ---- the rules, in Pine order (L791-829) ------------------------------------------------
    def on_bar(
        self, *, sid: int, in_session: bool, new_session: bool, session_ends: bool, high: float,
        low: float, close: float, next_up: float, next_dn: float, up_proj: bool, dn_proj: bool,
        bar_index: int, day: str, horizon: int,
    ) -> None:  # fmt: skip
        boundary = new_session or not in_session
        if self.p_state is not None and boundary:  # never resolve with tomorrow's gap
            self.session_cut[self.p_state] += 1
            self.p_state = None
        if boundary:
            self.prev_state = None
        if self.p_state is not None:
            up, dn = high >= self.p_up, low <= self.p_dn
            ps, done = self.p_state, True
            if up and dn:
                self.both_hit[ps] += 1
            elif up:
                self.hit_up[ps] += 1
            elif dn:
                self.hit_dn[ps] += 1
            elif bar_index - self.p_bar >= horizon:
                self.timed_out[ps] += 1
            elif session_ends:
                self.session_cut[ps] += 1
            else:
                done = False
            if done:
                self.p_state = None
        changed = self.prev_state is not None and sid != self.prev_state
        real = (
            next_up == next_up and next_dn == next_dn and next_dn < close < next_up
            and not up_proj and not dn_proj
        )  # fmt: skip
        if in_session and not session_ends and changed and real and self.p_state is None:
            self.p_state, self.p_up, self.p_dn, self.p_bar = sid, next_up, next_dn, bar_index
            if self.last_sample_day[sid] != day:  # one sampleDays increment per bucket per day
                self.sample_days[sid] += 1
                self.last_sample_day[sid] = day
        if in_session:
            self.prev_state = sid

    def stats(self, sid: int, use_prob: bool, min_n: int) -> Stats:
        up, dn, to, both, cut = (
            self.hit_up[sid], self.hit_dn[sid], self.timed_out[sid], self.both_hit[sid], self.session_cut[sid],
        )  # fmt: skip
        resolved, finished = up + dn, up + dn + to + both + cut
        return Stats(
            up, dn, to, both, cut, 1 if self.p_state is not None and self.p_state == sid else 0,
            self.sample_days[sid], resolved, finished,
            100.0 * up / resolved if resolved > 0 else None,
            100.0 * up / finished if finished > 0 else None,
            100.0 * (up + both + cut) / finished if finished > 0 else None,
            use_prob and finished >= min_n,
        )  # fmt: skip

    def state(self) -> dict[str, Any]:
        nan = self.p_up != self.p_up
        return {
            "hit_up": self.hit_up, "hit_dn": self.hit_dn, "timed_out": self.timed_out,
            "both_hit": self.both_hit, "session_cut": self.session_cut,
            "sample_days": self.sample_days, "last_sample_day": self.last_sample_day,
            "prev_state": self.prev_state, "p_state": self.p_state,
            "p_up": None if nan else self.p_up, "p_dn": None if nan else self.p_dn, "p_bar": self.p_bar,
        }  # fmt: skip

    def load(self, st: dict[str, Any]) -> None:
        for k in ("hit_up", "hit_dn", "timed_out", "both_hit", "session_cut", "sample_days",
                  "last_sample_day"):  # fmt: skip
            setattr(self, k, list(st[k]))
        self.prev_state, self.p_state, self.p_bar = st["prev_state"], st["p_state"], st["p_bar"]
        self.p_up = float("nan") if st["p_up"] is None else st["p_up"]
        self.p_dn = float("nan") if st["p_dn"] is None else st["p_dn"]


@register_slot("path")
def make_path(p: BaluParams) -> PathHistory:
    return PathHistory()


def session_ends(eng: Any, f: BarFrame) -> bool:
    """Pine `sessionEnds` L178: the last in-session bar (bar end reaches the session end)."""
    _, hi = session_minutes(eng.p.session_str)
    return bool(
        f.in_session
        and (
            bar_minutes_ist(f.bar.bar_end_utc) >= hi
            or is_last_bar_of_session(f.bar, eng.ctx.calendar)
        )
    )


@step(13)
def path_history(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    ph: PathHistory = eng.slots["path"]
    s = eng.slots["core"].s
    loc = f.extra["location"]
    sid = state_id(f.regime_idx, f.flow_state, loc.loc_idx)
    ends = session_ends(eng, f)
    f.extra["session_ends"], f.extra["state_id"] = ends, sid
    if p.use_prob:
        ph.on_bar(
            sid=sid, in_session=f.in_session, new_session=f.new_session, session_ends=ends,
            high=f.bar.high, low=f.bar.low, close=f.bar.close, next_up=loc.next_up,
            next_dn=loc.next_dn, up_proj=loc.next_up_proj, dn_proj=loc.next_dn_proj,
            bar_index=s.n_bars, day=eng.ctx.calendar.session_date(f.bar.bar_start_utc).isoformat(),
            horizon=p.prob_horizon,
        )  # fmt: skip
    st = ph.stats(sid, p.use_prob, p.prob_min_n)
    f.extra["stats"] = st
    f.out.plots.update(
        state_id=float(sid), n_up=float(st.n_up), n_dn=float(st.n_dn), n_timeout=float(st.n_timeout),
        n_both=float(st.n_both), n_cut=float(st.n_cut), n_pending=float(st.n_pending),
        sample_days=float(st.sample_days),
    )  # fmt: skip
