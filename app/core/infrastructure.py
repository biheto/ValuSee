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


class HttpMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration: dict[tuple[str, str], tuple[int, float]] = {}

    def observe(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        route = route if route.startswith("/") else "unmatched"
        with self._lock:
            self._requests[(method, route, status)] += 1
            count, total = self._duration.get((method, route), (0, 0.0))
            self._duration[(method, route)] = (count + 1, total + duration_seconds)

    def prometheus(self) -> str:
        lines = ["# HELP valuesee_http_requests_total HTTP requests by route and status", "# TYPE valuesee_http_requests_total counter"]
        with self._lock:
            for (method, route, status), value in sorted(self._requests.items()):
                lines.append(f'valuesee_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {value}')
            lines.extend(["# HELP valuesee_http_request_duration_seconds_sum Total HTTP request duration", "# TYPE valuesee_http_request_duration_seconds_sum counter"])
            for (method, route), (count, total) in sorted(self._duration.items()):
                labels = f'method="{method}",route="{route}"'
                lines.append(f"valuesee_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
                lines.append(f"valuesee_http_request_duration_seconds_count{{{labels}}} {count}")
        return "\n".join(lines) + "\n"


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


def infrastructure_health() -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
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
            queue = connection.channel().queue_declare(queue="valuesee.price-events", durable=True, passive=True)
            depth = int(queue.method.message_count)
            connection.close()
            checks["rabbitmq"] = {"status": "ok", "queue_depth": depth}
        except Exception as exc:
            checks["rabbitmq"] = {"status": "error", "detail": type(exc).__name__}
    endpoint = os.getenv("S3_ENDPOINT_URL", "").strip()
    if endpoint:
        try:
            import boto3

            client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=os.getenv("S3_ACCESS_KEY"), aws_secret_access_key=os.getenv("S3_SECRET_KEY"), region_name=os.getenv("S3_REGION", "us-east-1"))
            client.head_bucket(Bucket=os.getenv("S3_BUCKET", "valuesee-uploads"))
            checks["object_storage"] = {"status": "ok"}
        except Exception as exc:
            checks["object_storage"] = {"status": "error", "detail": type(exc).__name__}
    return checks


rate_limiter = RateLimiter()
http_metrics = HttpMetrics()
