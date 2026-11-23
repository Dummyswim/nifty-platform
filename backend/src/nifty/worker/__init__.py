"""Worker: poll loop over the `jobs` table (D07). `python -m nifty.worker`."""

import logging
import threading
import time
from typing import Any

from sqlalchemy import Engine

from nifty.db.jobs import claim_job, fail_job, finish_job, heartbeat, requeue_stale
from nifty.worker.handlers import HANDLERS, Handler

log = logging.getLogger("nifty.worker")
HEARTBEAT_S = 10.0
STALE_S = 60.0


def _beat(engine: Engine, job_id: int, stop: threading.Event, every: float) -> None:
    while not stop.wait(every):
        try:
            with engine.begin() as c:
                heartbeat(c, job_id)
        except Exception:  # a missed beat only risks a requeue; the job itself continues
            log.exception("heartbeat failed")


def process_one(
    engine: Engine,
    handlers: dict[str, Handler] | None = None,
    heartbeat_every: float = HEARTBEAT_S,
) -> bool:
    """Claim and run one job. Returns False when the queue is empty."""
    table = handlers if handlers is not None else HANDLERS
    with engine.begin() as c:
        job = claim_job(c)
    if job is None:
        return False
    stop = threading.Event()
    t = threading.Thread(target=_beat, args=(engine, job["id"], stop, heartbeat_every), daemon=True)
    t.start()
    try:
        handler = table.get(job["kind"])
        if handler is None:
            raise LookupError(f"no handler for kind {job['kind']!r}")
        with engine.begin() as c:
            ref = handler(c, job["payload"])
        stop.set()
        with engine.begin() as c:
            finish_job(c, job["id"], ref)
    except Exception as e:
        stop.set()
        log.warning("job %s failed: %s", job["id"], e)
        with engine.begin() as c:
            fail_job(c, job["id"], f"{type(e).__name__}: {e}")
    finally:
        stop.set()
    return True


def run_loop(
    engine: Engine,
    poll_s: float = 1.0,
    stale_s: float = STALE_S,
    stop: threading.Event | None = None,
) -> None:
    stop = stop or threading.Event()
    last_sweep = 0.0
    while not stop.is_set():
        if time.monotonic() - last_sweep > stale_s / 2:
            with engine.begin() as c:
                n = requeue_stale(c, stale_s)
            if n:
                log.warning("requeued %d stale job(s)", n)
            last_sweep = time.monotonic()
        if not process_one(engine):
            stop.wait(poll_s)


def main(argv: list[str] | None = None) -> int:
    from nifty.db.session import get_engine

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()
    try:
        import signal

        for s in (signal.SIGINT, signal.SIGTERM):
            signal.signal(s, lambda *_a: stop.set())
    except ValueError:  # not the main thread
        pass
    log.info("worker started")
    run_loop(get_engine(), stop=stop)
    return 0


__all__: list[Any] = ["process_one", "run_loop", "main"]
