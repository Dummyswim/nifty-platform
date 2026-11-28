import math

import pytest
from pydantic import ValidationError

from nifty.context.params import ContextParams
from nifty.context.vol import (
    band,
    expected_move_pts,
    fair_straddle_prem,
    interp_iv,
    realised_vol,
    verdict,
    vix_rank,
)

P = ContextParams()


def test_vix_rank_needs_200_prior_closes() -> None:
    assert vix_rank([10.0] * 199, 12) is None


def test_vix_rank_uses_last_252() -> None:
    rank = vix_rank([float(i) for i in range(1, 301)], 280.5)
    assert rank is not None
    assert round(rank, 1) == 92.1


def test_band_floor() -> None:
    assert band(14, 10, 1.0) == pytest.approx(1.4)
    assert band(8, 10, 1.0) == 1.0


def test_verdict_entry_band() -> None:
    assert verdict(15.3, 14, None, P) == "FAIR"
    assert verdict(15.5, 14, None, P) == "RICH"
    assert verdict(12.5, 14, None, P) == "CHEAP"


def test_verdict_hysteresis() -> None:
    assert verdict(15.6, 14, "FAIR", P) == "FAIR"
    assert verdict(15.9, 14, "FAIR", P) == "RICH"
    assert verdict(12.2, 14, "FAIR", P) == "FAIR"
    assert verdict(12.1, 14, "FAIR", P) == "CHEAP"


def test_verdict_hysteresis_rich_cheap() -> None:
    assert verdict(15.1, 14, "RICH", P) == "RICH"
    assert verdict(14.9, 14, "RICH", P) == "FAIR"
    assert verdict(12.9, 14, "CHEAP", P) == "CHEAP"
    assert verdict(13.1, 14, "CHEAP", P) == "FAIR"


def test_verdict_exit_floor_scales() -> None:
    # low VIX: exit floor 1.3 -> FAIR holds at +1.25, entry would say RICH
    assert verdict(9.25, 8, "FAIR", P) == "FAIR"
    assert verdict(9.25, 8, None, P) == "RICH"


def test_interp_iv_continuous_across_atm_switch() -> None:
    a = interp_iv(24999.9, (24950, 14.0), (25000, 15.0))
    b = interp_iv(25000.1, (25000, 15.0), (25050, 16.0))
    assert abs(a - b) < 0.01


def test_interp_iv_same_strike() -> None:
    assert interp_iv(25000, (25000, 15.0), (25000, 99.0)) == 15.0


def test_fair_straddle_and_expected_move() -> None:
    assert fair_straddle_prem(26000, 15, 2 / 365) == pytest.approx(230.9, abs=0.5)
    assert expected_move_pts(26000, 15) == pytest.approx(245.7, abs=0.1)


def test_realised_vol_within_sessions_only() -> None:
    s1 = [100.0, 101.0, 100.0]
    s2 = [200.0, 202.0, 200.0]
    rets = [math.log(101 / 100), math.log(100 / 101), math.log(202 / 200), math.log(200 / 202)]
    m = sum(rets) / 4
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / 3)
    assert realised_vol([s1, s2]) == pytest.approx(sd * math.sqrt(375 * 252) * 100)


def test_realised_vol_needs_two_sessions() -> None:
    assert realised_vol([[100.0, 101.0, 102.0]]) is None
    assert realised_vol([]) is None


def test_params_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        ContextParams.model_validate({"foo": 1})


@pytest.mark.parametrize(
    "bad",
    [
        {"band_pct": 0},
        {"band_pct": -1},
        {"exit_pct": 9},  # below band_pct 10
        {"vix_exit_pct": 71},  # above vix_pct 70
        {"w_exit": 0.51},  # above w_min 0.5
        {"roll_oppose": 0},
        {"roll_oppose": 1.1},
        {"confirm": 0},
        {"release": 0},
        {"roll_min": 0},
        {"strikes": 0},
        {"not_before": "9.30"},
        {"not_before": "25:00"},
        {"not_before": "09:30:00"},
    ],
)
def test_params_reject_inconsistent(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ContextParams.model_validate(bad)


def test_params_accept_boundaries() -> None:
    ContextParams.model_validate({"exit_pct": 10, "vix_exit_pct": 70, "w_exit": 0.5, "roll_oppose": 1,
                                  "confirm": 1, "release": 1, "roll_min": 1, "strikes": 1})  # fmt: skip


def test_params_per_rule_threshold_defaults() -> None:
    iv, oi = ContextParams(writing="iv"), ContextParams(writing="oi")
    assert (iv.w_min, iv.w_exit) == (0.5, 0.3) and (oi.w_min, oi.w_exit) == (0.25, 0.15)
    assert ContextParams(writing="oi", w_min=0.2).w_exit == 0.15
    assert ContextParams().roll_oppose == 0.5
