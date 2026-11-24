from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from nifty.api import auth, chart_routes, kite_routes, options_routes, routes, stream
from nifty.api.auth import Throttle
from nifty.db.session import get_engine
from nifty.engines.base import load_builtin_engines

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "alembic"  # backend/alembic (or /app/alembic)


@lru_cache
def head_revision() -> str | None:
    return ScriptDirectory(str(ALEMBIC_DIR)).get_current_head()


def create_app() -> FastAPI:
    app = FastAPI(title="NIFTY Platform", version="0.1.0")
    app.state.throttle = Throttle()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        try:
            head = head_revision()
            with get_engine().connect() as c:
                rev = c.execute(text("select version_num from alembic_version")).scalar()
        except Exception as e:
            raise HTTPException(503, "db unreachable or not migrated") from e
        if rev != head:
            raise HTTPException(503, f"migrations behind: {rev}")
        return {"status": "ready"}

    load_builtin_engines()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(chart_routes.router, prefix="/api/v1")
    app.include_router(kite_routes.router, prefix="/api/v1")
    app.include_router(options_routes.router, prefix="/api/v1")
    app.include_router(stream.router)
    return app
