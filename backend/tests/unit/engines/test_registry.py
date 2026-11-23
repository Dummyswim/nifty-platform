import subprocess
import sys

import pytest

from nifty.engines.base import (
    EngineNotFound,
    EngineNotReady,
    get_engine,
    list_engines,
    load_builtin_engines,
    register_engine,
    unregister_engine,
)
from tests.sma_cross_engine import SmaCross, registered


def test_register_get_list_and_schema() -> None:
    assert not [e for e in list_engines() if e["id"].startswith("test.")]
    with registered():
        spec = get_engine("test.sma_cross")
        assert spec.cls is SmaCross and spec.ready
        (entry,) = [e for e in list_engines() if e["id"] == "test.sma_cross"]
        assert (entry["version"], entry["default_timeframe"], entry["ready"]) == ("1", "5m", True)
        assert entry["schema"]["properties"]["ui"]["x-ui"] is True
    with pytest.raises(EngineNotFound):
        get_engine("test.sma_cross")  # unregistered again


def test_unready_engines_never_listed_and_need_an_explicit_flag() -> None:
    with registered(ready=False):
        assert all(e["id"] != "test.sma_cross" for e in list_engines())
        assert any(e["id"] == "test.sma_cross" for e in list_engines(include_unready=True))
        with pytest.raises(EngineNotReady):
            get_engine("test.sma_cross")
        assert get_engine("test.sma_cross", allow_unready=True).ready is False


def test_duplicate_id_with_other_class_rejected() -> None:
    class Other(SmaCross):
        pass

    with registered():
        register_engine(SmaCross)  # same class again is fine
        with pytest.raises(ValueError):
            register_engine(Other)
    unregister_engine("test.sma_cross")  # idempotent


def test_production_registry_has_no_test_engines() -> None:
    code = (
        "from nifty.engines.base import load_builtin_engines, list_engines\n"
        "load_builtin_engines()\n"
        "ids=[e['id'] for e in list_engines(include_unready=True)]\n"
        "assert not [i for i in ids if i.startswith('test.')], ids\n"
    )
    r = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stderr
    load_builtin_engines()  # explicit loader exists and is a no-op until engines land
