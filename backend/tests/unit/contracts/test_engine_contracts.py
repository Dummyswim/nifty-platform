import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nifty.contracts import (
    EngineEvent,
    config_hash,
    make_event_id,
    params_json_schema,
)
from tests.sma_cross_engine import SmaCrossParams

T = datetime(2026, 11, 2, 3, 45, tzinfo=UTC)


def test_config_hash_ignores_ui_but_not_params_or_version() -> None:
    base = config_hash("test.sma_cross", "1", SmaCrossParams())
    assert len(base) == 64
    ui_changed = SmaCrossParams.model_validate({"ui": {"color": "#ff0000", "show_markers": False}})
    assert config_hash("test.sma_cross", "1", ui_changed) == base
    assert config_hash("test.sma_cross", "1", SmaCrossParams(fast=4)) != base
    assert config_hash("test.sma_cross", "2", SmaCrossParams()) != base
    assert config_hash("other.id", "1", SmaCrossParams()) != base


def test_params_reject_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        SmaCrossParams.model_validate({"fastt": 9})
    with pytest.raises(ValidationError):
        SmaCrossParams.model_validate({"ui": {"colour": "x"}})


def test_json_schema_tags_ui_fields() -> None:
    schema = params_json_schema(SmaCrossParams)
    assert schema["properties"]["ui"]["x-ui"] is True
    assert "x-ui" not in schema["properties"]["fast"]
    ui_def = next(d for n, d in schema["$defs"].items() if "color" in d.get("properties", {}))
    assert ui_def["x-ui"] is True and all(p["x-ui"] for p in ui_def["properties"].values())
    json.dumps(schema, allow_nan=False)


def test_event_id_is_a_stable_uuid5() -> None:
    a = make_event_id("e", "h", "i", "5m", T, "signal", 0)
    assert a == make_event_id("e", "h", "i", "5m", T, "signal", 0)
    assert isinstance(a, uuid.UUID) and a.version == 5
    others = [
        make_event_id("e2", "h", "i", "5m", T, "signal", 0),
        make_event_id("e", "h2", "i", "5m", T, "signal", 0),
        make_event_id("e", "h", "i2", "5m", T, "signal", 0),
        make_event_id("e", "h", "i", "15m", T, "signal", 0),
        make_event_id("e", "h", "i", "5m", T, "entry", 0),
        make_event_id("e", "h", "i", "5m", T, "signal", 1),
        make_event_id("e", "h", "i", "5m", T, "signal", 0, provisional=True),
    ]
    assert len({a, *others}) == 8


def test_event_envelope_roundtrip() -> None:
    ev = EngineEvent(
        event_id=make_event_id("e", "h", "i", "5m", T, "signal", 0), event_type="signal",
        engine_id="e", engine_version="1", config_hash="h", instrument_id="i", source_id="live",
        timeframe="5m", event_time_utc=T, available_at_utc=T, bar_start_utc=T, bar_end_utc=T,
    )  # fmt: skip
    assert EngineEvent.model_validate_json(ev.model_dump_json()) == ev
