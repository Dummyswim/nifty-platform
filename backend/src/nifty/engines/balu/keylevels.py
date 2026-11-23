"""Step 9 (L577-625): day-scoped key-level rails. Overlays are `hline` elements `kl:<NAME>:<date>`,
created on the first bar of a session (previous rails get a `deleted` version first) and, for the
opening range, at `dayLen == orBars` on a confirmed in-session bar."""

from datetime import datetime
from typing import Any

from nifty.contracts import OverlayElement
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.session import or_bars
from nifty.engines.balu.steps import BarFrame, register_slot, step


class Rails:
    def __init__(self) -> None:
        self.active: list[list[Any]] = []  # [id, last ver, t0 iso, price, text, dash]

    def state(self) -> dict[str, Any]:
        return {"active": [list(r) for r in self.active]}

    def load(self, st: dict[str, Any]) -> None:
        self.active = [list(r) for r in st["active"]]


@register_slot("rails")
def make_rails(p: BaluParams) -> Rails:
    return Rails()


def _rail(f: BarFrame, rails: Rails, day: str, name: str, price: float, dash: str) -> None:
    if price != price:
        return  # NaN prices are skipped (e.g. no prior day on the first session)
    rid = f"kl:{name}:{day}"
    rails.active.append([rid, 0, f.bar.bar_start_utc.isoformat(), price, name, dash])
    f.out.overlay_ops.append(
        OverlayElement(
            id=rid, ver=0, kind="hline", t0=f.bar.bar_start_utc, t1=None, p0=price,
            style={"role": "info", "dash": dash}, text=name,
        )
    )  # fmt: skip


@step(9)
def key_levels(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    s = eng.slots["core"].s
    rails: Rails = eng.slots["rails"]
    day = eng.ctx.calendar.session_date(f.bar.bar_start_utc).isoformat()
    if p.show_key_levels and f.new_session:
        for r in rails.active:  # f_clearKeys: every previous rail goes away
            r[1] += 1
            f.out.overlay_ops.append(
                OverlayElement(
                    id=r[0], ver=r[1], deleted=True, kind="hline",
                    t0=datetime.fromisoformat(r[2]), p0=r[3], text=r[4],
                )
            )  # fmt: skip
        rails.active = []
        if p.kl_pdhl:
            _rail(f, rails, day, "PDH", f.pd_h, "solid")
            _rail(f, rails, day, "PDL", f.pd_l, "solid")
        if p.kl_pdc:
            _rail(f, rails, day, "PDC", f.pd_c, "dotted")
        if p.kl_pivot:
            _rail(f, rails, day, "PP", f.pp, "dashed")
            _rail(f, rails, day, "R1", f.r1, "dashed")
            _rail(f, rails, day, "S1", f.s1, "dashed")
    if p.show_key_levels and p.kl_or and f.in_session and s.day_len == or_bars(p, eng.tf_min):
        _rail(f, rails, day, "ORH", s.or_high, "dashed")
        _rail(f, rails, day, "ORL", s.or_low, "dashed")
