from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_MAX_AGE_SECONDS = 300


def cron_signature(secret: str, timestamp: str, method: str, path: str) -> str:
    message = f"{timestamp}\n{method.upper()}\n{path}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_cron_signature(
    secret: str,
    timestamp: str,
    signature: str,
    method: str,
    path: str,
    *,
    now: int | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        signed_at = int(timestamp)
    except ValueError:
        return False
    current_time = int(time.time()) if now is None else now
    if abs(current_time - signed_at) > max_age_seconds:
        return False
    expected = cron_signature(secret, timestamp, method, path)
    return hmac.compare_digest(signature.lower(), expected)
