"""Kite routes (D19): login URL, callback (token exchange stays server-side), status, jobs."""

import logging
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from nifty.api.auth import check_origin, require_user
from nifty.api.routes import SubmitOut, _job_out
from nifty.config import Settings, get_settings
from nifty.db.jobs import submit_job
from nifty.db.kite import kite_status, store_token
from nifty.db.session import get_engine
from nifty.marketdata.base import ProviderError
from nifty.marketdata.kite.client import KiteClient

log = logging.getLogger("nifty.api.kite")
router = APIRouter(prefix="/kite", dependencies=[Depends(require_user)])


class LoginUrlOut(BaseModel):
    url: str


class KiteStatusOut(BaseModel):
    configured: bool
    connected: bool
    user_id: str | None = None
    expires_at: datetime | None = None
    last_error: str | None = None
    instruments_updated_at: datetime | None = None


class BackfillIn(BaseModel):
    symbol: str = "NIFTY 50"
    from_date: date
    to_date: date


def _client(s: Settings) -> KiteClient:
    if not (s.kite_api_key and s.kite_api_secret):
        raise HTTPException(409, "KITE_API_KEY / KITE_API_SECRET are not set in .env")
    return KiteClient(s.kite_api_key, s.kite_api_secret)


@router.get("/login-url", response_model=LoginUrlOut)
def login_url(s: Settings = Depends(get_settings)) -> dict[str, str]:
    return {"url": _client(s).login_url()}


@router.get("/callback")
def callback(
    request_token: str | None = None, status: str | None = None, s: Settings = Depends(get_settings)
) -> RedirectResponse:
    """Kite redirects here with `request_token`; other params (`action`, `type`) are ignored. The
    exchange happens server-side and the browser is sent back to the UI by absolute URL."""
    ui = (s.origins or ["http://127.0.0.1:8080"])[0]

    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"{ui}/settings?{urlencode({'kite': result})}", status_code=303)

    if status != "success" or not request_token:
        return back("error")
    try:
        sess = _client(s).exchange_token(request_token)
        with get_engine().begin() as c:
            store_token(c, s.app_secret_key, sess["access_token"], sess["user_id"])
    except (ProviderError, HTTPException) as e:
        log.warning("kite callback failed: %s", e)
        return back("error")
    return back("connected")


@router.get("/status", response_model=KiteStatusOut)
def status(s: Settings = Depends(get_settings)) -> dict[str, Any]:
    with get_engine().begin() as c:
        return kite_status(c, s)


@router.post(
    "/instruments/refresh",
    status_code=202,
    response_model=SubmitOut,
    dependencies=[Depends(check_origin)],
)
def refresh_instruments() -> dict[str, Any]:
    with get_engine().begin() as c:  # nonce: a manual refresh must not dedupe onto an old job
        jid, created = submit_job(c, "kite_instruments", {"nonce": time.time_ns()})
        return _job_out(c, jid, created)


@router.post(
    "/backfill", status_code=202, response_model=SubmitOut, dependencies=[Depends(check_origin)]
)
def backfill(body: BackfillIn) -> dict[str, Any]:
    if body.to_date < body.from_date:
        raise HTTPException(422, "to_date is before from_date")
    with get_engine().begin() as c:
        payload = {"symbol": body.symbol, "from_date": body.from_date.isoformat(),
                   "to_date": body.to_date.isoformat(), "nonce": time.time_ns()}  # fmt: skip
        jid, created = submit_job(c, "kite_backfill", payload)
        return _job_out(c, jid, created)
