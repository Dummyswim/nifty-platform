from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from nifty.api import auth
from nifty.api.auth import Throttle
from nifty.db.session import get_engine

HEAD_REVISION = "0001"


def create_app() -> FastAPI:
    app = FastAPI(title="NIFTY Platform", version="0.1.0")
    app.state.throttle = Throttle()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        try:
            with get_engine().connect() as c:
                rev = c.execute(text("select version_num from alembic_version")).scalar()
        except Exception as e:
            raise HTTPException(503, "db unreachable or not migrated") from e
        if rev != HEAD_REVISION:
            raise HTTPException(503, f"migrations behind: {rev}")
        return {"status": "ready"}

    app.include_router(auth.router, prefix="/api/v1")
    return app
