from __future__ import annotations

import logging
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.core.infrastructure import (
    MONITOR_DEAD_QUEUE,
    MONITOR_QUEUE,
    MONITOR_RETRY_QUEUE,
    declare_monitor_queues,
)
from app.shopping.store import shopping_store
from app.shopping.monitor_collector import collect_public_monitor_updates


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("valuesee.shopping.worker")
running = True
stop_event = threading.Event()


def _stop(*_: object) -> None:
    global running
    running = False
    stop_event.set()


def run_once() -> dict[str, int]:
    collection = collect_public_monitor_updates(shopping_store)
    result = {**shopping_store.process_latest_snapshots(), **collection}
    logger.info(
        "monitor cycle processed=%s notifications=%s public_checked=%s pending_confirmations=%s",
        result["processed"], result["notifications"], result["public_checked"], result["pending_confirmations"],
    )
    return result


def consume_events(handler: Callable[[dict[str, Any]], None], limit: int = 100) -> dict[str, int]:
    url = os.getenv("RABBITMQ_URL", "").strip()
    if not url:
        return {"consumed": 0, "retried": 0, "dead_lettered": 0}
    import pika

    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()
    declare_monitor_queues(channel)
    channel.basic_qos(prefetch_count=min(max(1, limit), 100))
    counts = {"consumed": 0, "retried": 0, "dead_lettered": 0}
    max_retries = max(0, int(os.getenv("VALUSee_QUEUE_MAX_RETRIES", "5")))
    try:
        for _ in range(max(1, limit)):
            method, properties, body = channel.basic_get(queue=MONITOR_QUEUE, auto_ack=False)
            if method is None:
                break
            try:
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict) or payload.get("type") != "price_snapshot" or not payload.get("snapshot_id"):
                    raise ValueError("invalid price event")
                handler(payload)
                channel.basic_ack(method.delivery_tag)
                counts["consumed"] += 1
            except ValueError:
                channel.basic_nack(method.delivery_tag, requeue=False)
                counts["dead_lettered"] += 1
            except Exception:
                headers = dict(getattr(properties, "headers", None) or {})
                attempts = int(headers.get("x-valuesee-retries", 0)) + 1
                route = MONITOR_RETRY_QUEUE if attempts <= max_retries else MONITOR_DEAD_QUEUE
                headers["x-valuesee-retries"] = attempts
                channel.basic_publish(
                    exchange="",
                    routing_key=route,
                    body=body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                        headers=headers,
                        message_id=getattr(properties, "message_id", None),
                    ),
                )
                channel.basic_ack(method.delivery_tag)
                counts["retried" if route == MONITOR_RETRY_QUEUE else "dead_lettered"] += 1
    finally:
        connection.close()
    return counts


def handle_price_event(_: dict[str, Any]) -> None:
    # Snapshot IDs are durable in the database. Processing all latest snapshots
    # keeps delivery idempotent and lets the periodic scan recover missed events.
    run_once()


def write_heartbeat() -> None:
    path = Path(os.getenv("VALUSee_WORKER_HEARTBEAT_PATH", "/tmp/valuesee-worker-heartbeat"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    interval = max(10, int(os.getenv("VALUSee_MONITOR_INTERVAL_SECONDS", "60")))
    logger.info("ValuSee monitor worker started interval=%ss", interval)
    while running:
        try:
            queue_result = consume_events(handle_price_event)
            if queue_result["consumed"] == 0:
                run_once()
            if queue_result["retried"] or queue_result["dead_lettered"]:
                logger.warning("queue cycle result=%s", queue_result)
        except Exception:
            logger.exception("monitor cycle failed")
        finally:
            write_heartbeat()
        stop_event.wait(interval)


if __name__ == "__main__":
    main()
