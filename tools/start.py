"""`make start`: run the whole app from ONE terminal (migrate, API, worker, web, optional live
collector), with prefixed logs. Ctrl+C stops everything. Needs Postgres running (Redis optional).

  make start            API :8000 + worker + web :8080
  make start ARGS=--live    also the Kite live collector (Settings -> Connect Kite first)
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND, WEB = REPO / "backend", REPO / "web"
COLORS = {"api": "36", "worker": "33", "web": "35", "live": "32", "setup": "37"}
procs: list[subprocess.Popen[str]] = []


def say(tag: str, msg: str) -> None:
    c = COLORS.get(tag, "37")
    print(f"\033[{c}m[{tag:<6}]\033[0m {msg}", flush=True)


def pump(tag: str, p: subprocess.Popen[str]) -> None:
    assert p.stdout is not None
    for line in p.stdout:
        say(tag, line.rstrip())


def spawn(tag: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    p = subprocess.Popen(
        cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )  # fmt: skip
    threading.Thread(target=pump, args=(tag, p), daemon=True).start()
    procs.append(p)
    return p


def stop_all() -> None:
    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 8
    for p in procs:
        try:
            p.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)


def db_ready() -> bool:
    sys.path.insert(0, str(BACKEND / "src"))
    from sqlalchemy import create_engine, text

    from nifty.config import get_settings

    try:
        eng = create_engine(get_settings().database_url, connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def web_stale() -> bool:
    dist = WEB / "dist" / "index.html"
    if not dist.exists():
        return True
    newest = max((p.stat().st_mtime for p in (WEB / "src").rglob("*") if p.is_file()), default=0)
    return newest > dist.stat().st_mtime


def wait_for(url: str, secs: float = 45) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also run the Kite live collector")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=8080)
    ap.add_argument("--rebuild", action="store_true", help="force a web rebuild")
    a = ap.parse_args()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    def on_term(*_: object) -> None:
        raise KeyboardInterrupt  # SIGTERM stops the stack as cleanly as Ctrl+C

    signal.signal(signal.SIGTERM, on_term)

    if not db_ready():
        say("setup", "Postgres is not reachable. Start it first (WSL: `sudo service postgresql start`), then retry.")
        return 2
    say("setup", "database reachable; applying migrations")
    if subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True).returncode:
        say("setup", "migration failed: run `make migrate` to see the error")
        return 2
    if a.rebuild or web_stale():
        say("setup", "building the web app (npm run build)")
        if subprocess.run(["npm", "run", "build", "--silent"], cwd=WEB, env=env).returncode:
            return 2

    try:
        spawn("api", [sys.executable, "-m", "uvicorn", "nifty.api.main:create_app", "--factory",
                      "--host", "127.0.0.1", "--port", str(a.api_port)], BACKEND, env)  # fmt: skip
        spawn("worker", [sys.executable, "-m", "nifty.worker"], BACKEND, env)
        spawn("web", ["npx", "vite", "preview", "--host", "127.0.0.1", "--port", str(a.web_port),
                      "--strictPort"], WEB, {**env, "E2E_API_PORT": str(a.api_port)})  # fmt: skip
        if a.live:
            spawn("live", [sys.executable, "-m", "nifty.collector"], BACKEND, env)
        if wait_for(f"http://127.0.0.1:{a.api_port}/readyz") and wait_for(f"http://127.0.0.1:{a.web_port}/"):
            say("setup", f"READY: open http://127.0.0.1:{a.web_port}  (use 127.0.0.1, not localhost). Ctrl+C stops everything.")
        else:
            say("setup", "something did not start; see the logs above")
        while True:
            time.sleep(1)
            dead = [p for p in procs if p.poll() is not None]
            if dead and not a.live:
                say("setup", "a service exited; stopping")
                return 1
            if a.live and len(dead) == len(procs):
                return 1
    except KeyboardInterrupt:
        say("setup", "stopping…")
        return 0
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
