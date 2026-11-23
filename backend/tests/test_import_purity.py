import subprocess
import sys

CORE = (
    "nifty.contracts, nifty.timeutil, nifty.engines, nifty.execution, nifty.analytics, "
    "nifty.marketdata.importer, nifty.marketdata.validation, nifty.marketdata.resample, "
    "nifty.marketdata.providers.csv_replay, nifty.contracts.engine, nifty.engines.base, "
    "nifty.engines.context, nifty.engines.runner, nifty.engines.pinekit, "
    "nifty.engines.pinekit.indicators, nifty.engines.pinekit.session, nifty.execution.barriers, "
    "nifty.execution.broker, nifty.analytics.metrics, nifty.analytics.export"
)
BANNED = ["sqlalchemy", "fastapi", "redis", "nifty.api", "nifty.db"]


def test_core_imports_are_pure() -> None:
    code = (
        f"import {CORE}, sys; "
        f"bad=[m for m in {BANNED!r} if m in sys.modules]; "
        "print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"core imported: {r.stdout}{r.stderr}"
