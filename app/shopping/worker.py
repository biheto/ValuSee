from __future__ import annotations

import logging
import os
import signal
import time

from app.shopping.store import shopping_store


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("valuesee.shopping.worker")
running = True


def _stop(*_: object) -> None:
    global running
    running = False


def run_once() -> dict[str, int]:
    result = shopping_store.process_latest_snapshots()
    logger.info("monitor cycle processed=%s notifications=%s", result["processed"], result["notifications"])
    return result


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    interval = max(10, int(os.getenv("VALUSee_MONITOR_INTERVAL_SECONDS", "60")))
    logger.info("ValuSee monitor worker started interval=%ss", interval)
    while running:
        try:
            run_once()
        except Exception:
            logger.exception("monitor cycle failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
