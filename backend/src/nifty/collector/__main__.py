import asyncio
import logging

from nifty.collector.kite_run import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
raise SystemExit(asyncio.run(run()))
