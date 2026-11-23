import re
from pathlib import Path

PATTERN = re.compile(r"/orders|/gtt|place_order|modify_order|cancel_order|/basket")


def test_no_order_endpoints_in_src() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    hits = [
        f"{p}:{i}"
        for p in src.rglob("*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert hits == []
