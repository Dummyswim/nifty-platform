"""`make e2e`: seed `nifty_test` with the oracle CSV, start the API, the worker and the built SPA on spare
ports with a temporary password, run Playwright, stop everything. Never touches the dev DB; do not
run it at the same time as pytest (both use `nifty_test`).

Env: E2E_SHOT=<png path> saves a 1280x800 screenshot (default: none).
Browser: `cd web && npx playwright install chromium` once. If chromium lacks system libraries and
there is no sudo, extract them locally (no root needed):
  mkdir -p tools/.e2e-libs && cd tools/.e2e-libs && apt-get download libnspr4 libnss3 libasound2t64 \
  && for d in *.deb; do dpkg-deb -x "$d" .; done
(this script then adds tools/.e2e-libs/usr/lib/x86_64-linux-gnu to LD_LIBRARY_PATH)."""

import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def seed() -> str:
    """Create/migrate/truncate/seed nifty_test; return its URL (never printed)."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from nifty.config import get_settings
    from nifty.contracts import Instrument
    from nifty.db.bars import upsert_bars
    from nifty.db.instruments import upsert_instrument
    from nifty.marketdata.importer import parse_csv
    from nifty.marketdata.validation import validate_bars
    from nifty.timeutil import Calendar

    base = make_url(get_settings().database_url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.execute(text("select 1 from pg_database where datname='nifty_test'")).scalar():
            c.execute(text("create database nifty_test"))
    admin.dispose()
    url = base.set(database="nifty_test").render_as_string(hide_password=False)
    eng = create_engine(url)
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO / "backend" / "alembic"))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        conn.execute(
            text(
                "TRUNCATE kite_tokens, instrument_masters, drawings, trades, backtests, jobs, events, overlay_elements, plot_points, "
                "engine_runs, engine_configs, bars, datasets, instruments, prefs RESTART IDENTITY CASCADE"
            )
        )
        ins = Instrument(
            instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
        )
        upsert_instrument(conn, ins)
        bars, _ = validate_bars(
            parse_csv(REPO / "reference/oracle/data/nifty_1m.csv", instrument_id=ins.instrument_id),
            Calendar.load(),
        )
        upsert_bars(conn, bars)
    eng.dispose()
    return url


def wait(url: str, secs: float = 40) -> None:
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.3)
    raise SystemExit(f"timeout waiting for {url}")


def main() -> int:
    from nifty.security import hash_password

    db_url = seed()
    api_port, web_port = free_port(), free_port()
    password = secrets.token_urlsafe(12)
    origin = f"http://127.0.0.1:{web_port}"
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "APP_PASSWORD_HASH": hash_password(password),
        "APP_SECRET_KEY": secrets.token_hex(16),
        "APP_ORIGINS": origin,
        "E2E_API_PORT": str(api_port),
    }
    procs: list[subprocess.Popen[bytes]] = []

    def start(cmd: list[str], cwd: Path) -> None:
        procs.append(
            subprocess.Popen(
                cmd, cwd=cwd, env=env, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        )  # fmt: skip

    try:
        web = REPO / "web"
        if subprocess.run(["npm", "run", "build", "--silent"], cwd=web, env=env).returncode:
            return 1
        start([sys.executable, "-m", "uvicorn", "nifty.api.main:create_app", "--factory",
               "--host", "127.0.0.1", "--port", str(api_port)], REPO / "backend")  # fmt: skip
        start([sys.executable, "-m", "nifty.worker"], REPO / "backend")
        start(["npx", "vite", "preview", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], web)
        wait(f"http://127.0.0.1:{api_port}/readyz")
        wait(origin + "/")
        run_env = {**env, "E2E_BASE": origin, "E2E_PASSWORD": password}
        libs = REPO / "tools" / ".e2e-libs" / "usr" / "lib" / "x86_64-linux-gnu"
        if libs.is_dir():  # chromium libs fetched without root, see docstring
            run_env["LD_LIBRARY_PATH"] = f"{libs}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        return subprocess.run(["npx", "playwright", "test"], cwd=web, env=run_env).returncode
    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


if __name__ == "__main__":
    raise SystemExit(main())
