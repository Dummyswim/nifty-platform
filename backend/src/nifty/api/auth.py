import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from nifty.config import Settings, get_settings
from nifty.security import SESSION_TTL_S, read_session, sign_session, verify_password

COOKIE = "nifty_session"
MAX_FAILURES = 5
LOCKOUT_S = 60

router = APIRouter(prefix="/auth", tags=["auth"])


class Throttle:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.failures = 0
        self.locked_until = 0.0

    def locked(self) -> bool:
        return self.clock() < self.locked_until

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            self.locked_until = self.clock() + LOCKOUT_S
            self.failures = 0

    def ok(self) -> None:
        self.failures = 0


class LoginBody(BaseModel):
    password: str


class Me(BaseModel):
    user_id: int


def settings_dep() -> Settings:
    return get_settings()


def check_origin(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.origins:
        raise HTTPException(403, "bad origin")


def require_json(request: Request) -> None:
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "JSON only")


def require_user(request: Request, settings: Settings = Depends(settings_dep)) -> int:
    token = request.cookies.get(COOKIE)
    uid = (
        read_session(settings.app_secret_key, token) if token and settings.app_secret_key else None
    )
    if uid is None:
        raise HTTPException(401, "not authenticated")
    return uid


@router.post(
    "/login", response_model=Me, dependencies=[Depends(check_origin), Depends(require_json)]
)
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    settings: Settings = Depends(settings_dep),
) -> Any:
    throttle: Throttle = request.app.state.throttle
    if not settings.app_password_hash:
        raise HTTPException(503, "password not set")
    if throttle.locked():
        raise HTTPException(429, "too many failures; try later")
    if not verify_password(body.password, settings.app_password_hash):
        throttle.fail()
        raise HTTPException(401, "wrong password")
    throttle.ok()
    response.set_cookie(
        COOKIE,
        sign_session(settings.app_secret_key),
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return Me(user_id=1)


@router.post("/logout", dependencies=[Depends(check_origin), Depends(require_json)])
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=Me)
def me(uid: int = Depends(require_user)) -> Me:
    return Me(user_id=uid)
