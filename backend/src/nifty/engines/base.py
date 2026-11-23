"""Engine protocol and registry (D04, D14).

How to register an engine (production): add the module to `load_builtin_engines()` and call
`register_engine(MyEngine, ready=...)` at import time. `ready=False` engines are hidden from
`list_engines()` (so never reach the API/UI) and need `allow_unready=True` to be fetched.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol

from nifty.contracts.engine import EngineOutput, EngineParams, PlotSpec, params_json_schema

if TYPE_CHECKING:
    from nifty.contracts import Bar
    from nifty.engines.context import EngineContext


class Engine(Protocol):
    id: str
    version: str
    default_timeframe: str
    Params: type[EngineParams]
    plots: list[PlotSpec]
    warmup_bars: int

    def __init__(self, params: Any, ctx: "EngineContext") -> None: ...

    def on_bar(self, bar: "Bar") -> EngineOutput: ...

    def on_provisional(self, bar: "Bar") -> EngineOutput: ...

    def snapshot(self) -> dict[str, Any]: ...

    def restore(self, snap: dict[str, Any]) -> None: ...

    def panel(self) -> dict[str, Any] | None: ...


class EngineNotFound(KeyError):
    pass


class EngineNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineSpec:
    # any class satisfying the Engine protocol (mypy cannot express the class attributes)
    cls: type[Any]
    ready: bool = True

    @property
    def id(self) -> str:
        return str(self.cls.id)


_REGISTRY: dict[str, EngineSpec] = {}


def register_engine(cls: type[Any], ready: bool = True) -> type[Any]:
    if cls.id in _REGISTRY and _REGISTRY[cls.id].cls is not cls:
        raise ValueError(f"engine id already registered: {cls.id}")
    _REGISTRY[cls.id] = EngineSpec(cls, ready)
    return cls


def unregister_engine(engine_id: str) -> None:
    _REGISTRY.pop(engine_id, None)


def get_engine(engine_id: str, allow_unready: bool = False) -> EngineSpec:
    spec = _REGISTRY.get(engine_id)
    if spec is None:
        raise EngineNotFound(engine_id)
    if not spec.ready and not allow_unready:
        raise EngineNotReady(f"{engine_id} is not ready")
    return spec


def list_engines(include_unready: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "id": s.cls.id,
            "version": s.cls.version,
            "default_timeframe": s.cls.default_timeframe,
            "schema": params_json_schema(s.cls.Params),
            "plots": [pl.model_dump() for pl in s.cls.plots],
            "ready": s.ready,
        }
        for s in sorted(_REGISTRY.values(), key=lambda s: s.cls.id)
        if s.ready or include_unready
    ]


BUILTIN_ENGINE_MODULES: list[str] = ["nifty.engines.nvs", "nifty.engines.balu"]  # C13 research


def load_builtin_engines() -> None:
    for m in BUILTIN_ENGINE_MODULES:
        import_module(m)
