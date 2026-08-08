from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any


class RateLimiter:
    def __init__(self) -> None:
        self._local: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int = 120, window_seconds: int = 60) -> bool:
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, socket_timeout=1)
                bucket = f"valuesee:rate:{key}:{int(time.time()) // window_seconds}"
                count = client.incr(bucket)
                if count == 1:
                    client.expire(bucket, window_seconds + 1)
                return int(count) <= limit
            except Exception:
                if os.getenv("APP_ENV", "dev").lower() in {"prod", "production"}:
                    return False

        now = time.time()
        with self._lock:
            events = self._local[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


def publish_monitor_event(payload: dict[str, Any]) -> bool:
    url = os.getenv("RABBITMQ_URL", "").strip()
    if not url:
        return False
    try:
        import pika

        connection = pika.BlockingConnection(pika.URLParameters(url))
        channel = connection.channel()
        channel.queue_declare(queue="valuesee.price-events", durable=True)
        channel.basic_publish(
            exchange="",
            routing_key="valuesee.price-events",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        connection.close()
        return True
    except Exception:
        return False


def infrastructure_health() -> dict[str, dict[str, str]]:
    checks: dict[str, dict[str, str]] = {}
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            import redis

            redis.Redis.from_url(redis_url, socket_timeout=1).ping()
            checks["redis"] = {"status": "ok"}
        except Exception as exc:
            checks["redis"] = {"status": "error", "detail": type(exc).__name__}
    rabbit_url = os.getenv("RABBITMQ_URL", "").strip()
    if rabbit_url:
        try:
            import pika

            connection = pika.BlockingConnection(pika.URLParameters(rabbit_url))
            connection.close()
            checks["rabbitmq"] = {"status": "ok"}
        except Exception as exc:
            checks["rabbitmq"] = {"status": "error", "detail": type(exc).__name__}
    return checks


rate_limiter = RateLimiter()
