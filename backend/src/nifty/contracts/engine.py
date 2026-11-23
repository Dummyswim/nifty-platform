"""Engine-facing contracts (spec/01): events, overlays, trades, plots, params, config_hash."""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Fixed namespace so event_ids are reproducible across processes and machines.
EVENT_NAMESPACE = uuid.UUID("6b0f1c52-3f3e-5a4e-9d57-7a1e0c2b8a10")


class PlotSpec(BaseModel, frozen=True):
    name: str
    kind: Literal["line", "step", "hist", "area"] = "line"
    role: str = "neutral"
    pane: Literal["overlay", "own"] = "own"


class EngineEvent(BaseModel):
    schema_version: int = 1
    event_id: uuid.UUID
    seq: int = 0
    event_type: str
    engine_id: str
    engine_version: str
    config_hash: str
    instrument_id: str
    source_id: str  # snapshot_id | "live"
    timeframe: str
    event_time_utc: datetime
    available_at_utc: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime
    confirmed_or_provisional: Literal["confirmed", "provisional"] = "confirmed"
    price_basis: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def make_event_id(
    engine_id: str,
    config_hash: str,
    instrument_id: str,
    timeframe: str,
    bar_start_utc: datetime,
    event_type: str,
    seq: int,
    provisional: bool = False,
) -> uuid.UUID:
    name = "|".join(
        [engine_id, config_hash, instrument_id, timeframe, bar_start_utc.isoformat(), event_type]
        + [str(seq)]
        + (["provisional"] if provisional else [])
    )
    return uuid.uuid5(EVENT_NAMESPACE, name)


class OverlayElement(BaseModel):
    """Renderer-agnostic, event-sourced. The runner stamps engine_id and avail_at_utc."""

    id: str
    ver: int = 0
    deleted: bool = False
    avail_at_utc: datetime | None = None
    engine_id: str = ""
    kind: Literal["line", "step_line", "hline", "band", "zone", "marker", "label", "region"]
    t0: datetime
    t1: datetime | None = None
    p0: float | None = None
    p1: float | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TradeRecord(BaseModel):
    trade_id: str
    engine_id: str
    instrument_id: str
    side: Literal["long", "short"]
    signal_bar_start: datetime | None = None
    entry_time: datetime
    entry_px: float
    exit_time: datetime
    exit_px: float
    exit_reason: str
    qty: float = 1.0
    gross_pts: float
    cost_pts: float = 0.0
    net_pts: float
    r_multiple: float | None = None
    mae_pts: float = 0.0
    mfe_pts: float = 0.0
    bars_held: int = 1
    execution_mode: Literal["tv", "conservative"] = "tv"
    flags: list[str] = Field(default_factory=list)
    # option paper trades (C12)
    contract_id: str | None = None
    entry_prem: float | None = None
    exit_prem: float | None = None
    pnl_inr: float | None = None
    roi_pct: float | None = None
    synthetic: bool = False


@dataclass
class Ev:
    """What an engine returns for an event; the runner builds the envelope."""

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    price_basis: str | None = None


@dataclass
class EngineOutput:
    plots: dict[str, float | None] = field(default_factory=dict)
    events: list[Ev] = field(default_factory=list)
    overlay_ops: list[OverlayElement] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)


class UiParams(BaseModel):
    """Presentation-only parameters (colours, toggles). Excluded from config_hash."""

    model_config = ConfigDict(extra="forbid")


class EngineParams(BaseModel):
    """Base for engine params. Unknown keys are errors so a typo can never dedupe onto defaults."""

    model_config = ConfigDict(extra="forbid")
    ui: UiParams = Field(default_factory=UiParams)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def config_hash(engine_id: str, engine_version: str, params: EngineParams) -> str:
    body = {
        "engine_id": engine_id,
        "engine_version": engine_version,
        "params": params.model_dump(mode="json", exclude={"ui"}),
    }
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def params_json_schema(params_cls: type[EngineParams]) -> dict[str, Any]:
    """JSON Schema for the UI form; everything under `ui` is tagged `x-ui: true`."""
    schema = params_cls.model_json_schema()
    props = schema.get("properties", {})
    ui = props.get("ui")
    if ui is None:
        return schema
    ui["x-ui"] = True
    refs = [ui["$ref"]] if "$ref" in ui else [a["$ref"] for a in ui.get("allOf", []) if "$ref" in a]
    for ref in refs:
        d = schema.get("$defs", {}).get(ref.rsplit("/", 1)[-1])
        if d is not None:
            d["x-ui"] = True
            for p in d.get("properties", {}).values():
                p["x-ui"] = True
    return schema
