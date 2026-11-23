"""Step 4: golden source, deadband hysteresis, regime and session resets (L314-357)."""

import math
from typing import Any

import pytest

from tests.unit.engines.balu.helpers import D1, D2, D3, OHLC, Harness

PP: dict[str, Any] = dict(gold_source="Daily Pivot (PP)", use_htf_levels=False)


def around(c: float) -> OHLC:
    return (c, c + 1, c - 1, c)  # range 2 and |c - previous close| <= 1 keep TR = 2 => ATR = 2


def test_deadband_hysteresis_regime_and_session_reset() -> None:
    h = Harness(**PP)
    h.day(D1, [(100, 101, 99, 100)] * 20)  # ATR = 2; prior day H 101 / L 99 / C 100 => PP = 100
    h.day(D2, [around(c) for c in (100.6, 100.2, 99.6, 99.4, 100.0)])
    h.day(D3, [around(100.2)])
    # deadband = 2 * 0.25 = 0.5: flips above 100.5 / below 99.5, otherwise the state is kept
    assert h.plot("gold_state")[20:25] == [1.0, 1.0, 1.0, -1.0, -1.0]
    assert (
        h.plot("gold_state")[:20] == [0.0] * 20
    )  # PP is NaN on the first session: nothing compares true
    assert (
        h.plot("gold_state")[25] == 0.0
    )  # the new session resets the state; 100.2 is inside the band
    # dayLen <= flowSlopeLen so the slope is 0: BULL while state > 0, BEAR while state < 0
    assert h.plot("regime_idx")[20:25] == [2.0, 2.0, 2.0, 0.0, 0.0]
    assert h.plot("regime_idx")[25] == 1.0 and set(h.plot("regime_idx")[:20]) == {1.0}


def test_golden_line_breaks_at_each_session_open() -> None:
    h = Harness(**PP)
    h.day(D1, [(100, 101, 99, 100)] * 3)
    h.day(D2, [(100, 101, 99, 100)] * 3)
    g = h.plot("golden")
    assert all(math.isnan(x) for x in g[:3])  # day 1: PP is NaN
    assert math.isnan(g[3]) and g[4] == g[5] == 100.0  # day 2: NaN on the first bar, then PP
    assert h.plot("gold_val")[3] == 100.0  # the underlying value is still there


def test_no_volume_falls_back_to_twap_and_regime_works() -> None:
    h = Harness(use_htf_levels=False)
    h.day(D1, [(100, 101, 99, 100), (100, 103, 101, 102), (102, 105, 103, 104)])
    # TWAP = running mean of hlc3: (100 + (103+101+102)/3 + (105+103+104)/3) / 3 for the third bar
    hlc3 = [100.0, 102.0, 104.0]
    assert h.plot("gold_val") == pytest.approx([sum(hlc3[: i + 1]) / (i + 1) for i in range(3)])
    assert h.engine.slots["core"].s.vol_seen is False  # type: ignore[attr-defined]


def test_vwap_switches_when_volume_first_appears_and_vol_seen_is_sticky() -> None:
    from datetime import timedelta

    from nifty.contracts import Bar
    from tests.helpers import CAL, NOW

    h = Harness(use_htf_levels=False)
    open_, _ = CAL.session_bounds(D1)

    def feed(i: int, vol: float, hlc: tuple[float, float, float]) -> float:
        start = open_ + timedelta(minutes=5 * i)
        for k in range(5):
            from tests.unit.engines.balu.helpers import bar1

            h.ctx.append_1m(
                bar1(start + timedelta(minutes=k), hlc[2], hlc[0], hlc[1], hlc[2], "1m", 1)
            )
        b = Bar(
            instrument_id="csv:T", provider="csv", timeframe="5m", bar_start_utc=start,
            bar_end_utc=start + timedelta(minutes=5), open=hlc[2], high=hlc[0], low=hlc[1],
            close=hlc[2], volume=vol, volume_kind="exchange", received_at_utc=NOW,
        )  # fmt: skip
        return float(h.engine.on_bar(b).plots["gold_val"])  # type: ignore[arg-type]

    assert feed(0, 0.0, (103, 97, 100)) == pytest.approx(100.0)  # (103+97+100)/3 = 100, TWAP
    v = feed(1, 50.0, (106, 100, 103))  # hlc3 = 103; volume appears: weighted by 50 only
    assert v == pytest.approx(103.0)  # PV/W = 103*50/50: the TWAP history is dropped from the line
    assert h.engine.slots["core"].s.vol_seen is True  # type: ignore[attr-defined]
    assert feed(2, 0.0, (100, 94, 97)) == pytest.approx(103.0)  # weighted branch stays (W > 0)
