from nifty.context.writing import Leg, one_sided, raw_oi, score, writing_qty


def leg(
    is_call: bool, oi: float, prem: float, oi_base: float = 0.0, prem_base: float = 10.0
) -> Leg:
    return Leg(is_call=is_call, oi=oi, prem=prem, oi_base=oi_base, prem_base=prem_base)


def test_writing_qty_oi_up_premium_down() -> None:
    assert writing_qty(leg(True, 100, 5)) == 100


def test_writing_qty_buying_is_not_writing() -> None:
    assert writing_qty(leg(True, 100, 15)) == 0.0


def test_writing_qty_oi_down_is_zero() -> None:
    assert writing_qty(leg(True, 50, 5, oi_base=100)) == 0.0


def test_score_call_heavy_is_negative() -> None:
    legs = [leg(True, 300, 5), leg(False, 100, 5)]
    assert score(legs) == -0.5


def test_score_nothing_is_zero() -> None:
    assert score([]) == 0.0
    assert score([leg(True, 100, 15)]) == 0.0


def test_raw_oi_has_no_price_filter() -> None:
    legs = [leg(True, 100, 15), leg(False, 40, 5), leg(False, 30, 5, oi_base=50)]
    assert raw_oi(legs) == (100, 20)


def test_one_sided() -> None:
    assert one_sided(-0.46, -0.52, 0.3) == -1
    assert one_sided(-0.46, 0.2, 0.3) == 0
    assert one_sided(-0.46, 0.0, 0.3) == -1
    assert one_sided(0.29, 0.5, 0.3) == 0
    assert one_sided(0.46, 0.5, 0.3) == 1
