import pytest

from nifty.contracts import Prem, Pts, R, UnitMismatch


def test_same_unit_ok() -> None:
    s = Pts(1.5) + Pts(2.0)
    assert isinstance(s, Pts) and s == 3.5
    assert isinstance(Pts(3) - 1, Pts)
    assert isinstance(1 + Pts(3), Pts)


def test_mixed_units_raise() -> None:
    with pytest.raises(UnitMismatch):
        Pts(1) + Prem(1)
    with pytest.raises(UnitMismatch):
        Prem(1) - Pts(1)
    with pytest.raises(UnitMismatch):
        R(1) + Pts(1)
