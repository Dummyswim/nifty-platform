from nifty.context.writing import Leg, one_sided, raw_oi, score_iv, score_oi, writing_qty_iv


def leg(
    is_call: bool, oi: float, oi_base: float = 0.0, iv: float | None = 13.5,
    iv_base: float | None = 14.0,
) -> Leg:  # fmt: skip
    return Leg(is_call=is_call, oi=oi, oi_base=oi_base, iv=iv, iv_base=iv_base)


def test_writing_qty_iv_oi_up_iv_down() -> None:
    assert writing_qty_iv(leg(True, 100)) == 100


def test_writing_qty_iv_flat_iv_counts() -> None:
    assert writing_qty_iv(leg(True, 100, iv=14.0)) == 100


def test_writing_qty_iv_tolerates_small_iv_rise() -> None:
    assert writing_qty_iv(leg(True, 100, iv=14.04)) == 100  # within IV_TOL of 14.0
    assert writing_qty_iv(leg(True, 100, iv=14.06)) == 0.0


def test_writing_qty_iv_rising_iv_is_not_writing() -> None:
    assert writing_qty_iv(leg(True, 100, iv=14.5)) == 0.0


def test_writing_qty_iv_missing_iv_is_zero() -> None:
    assert writing_qty_iv(leg(True, 100, iv=None)) == 0.0
    assert writing_qty_iv(leg(True, 100, iv_base=None)) == 0.0


def test_writing_qty_iv_oi_down_is_zero() -> None:
    assert writing_qty_iv(leg(True, 50, oi_base=100)) == 0.0


def test_score_iv_call_heavy_is_negative() -> None:
    assert score_iv([leg(True, 300), leg(False, 100)]) == -0.5


def test_score_iv_nothing_is_zero() -> None:
    assert score_iv([]) == 0.0
    assert score_iv([leg(True, 100, iv=15.0)]) == 0.0


def test_score_oi_has_no_iv_filter() -> None:
    assert score_oi([leg(True, 300, iv=20.0), leg(False, 100, iv=None)]) == -0.5
    assert score_oi([leg(True, 300), leg(False, 0, oi_base=100)]) == -1.0  # (-100-300)/(100+300)
    assert score_oi([leg(True, 100, oi_base=100), leg(False, 0)]) == 0.0
    assert score_oi([]) == 0.0


def test_raw_oi_has_no_filter() -> None:
    legs = [leg(True, 100, iv=15.0), leg(False, 40), leg(False, 30, oi_base=50)]
    assert raw_oi(legs) == (100, 20)


def test_one_sided() -> None:
    assert one_sided(-0.46, -0.52, 0.3) == -1
    assert one_sided(-0.46, 0.2, 0.3) == 0
    assert one_sided(-0.46, 0.0, 0.3) == -1
    assert one_sided(0.29, 0.5, 0.3) == 0
    assert one_sided(0.46, 0.5, 0.3) == 1
