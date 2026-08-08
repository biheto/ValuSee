from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.request import Request, urlopen


def deliver_notification(notification: dict[str, object]) -> str:
    """Deliver an optional server-to-server webhook; durable in-app storage remains canonical."""
    endpoint = os.getenv("VALUSee_NOTIFICATION_WEBHOOK_URL", "").strip()
    if not endpoint:
        return "in_app_only"
    body = json.dumps(notification, ensure_ascii=False).encode("utf-8")
    secret = os.getenv("VALUSee_NOTIFICATION_WEBHOOK_SECRET", "").encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest() if secret else ""
    request = Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ValuSee-Signature": signature,
    })
    try:
        with urlopen(request, timeout=5) as response:
            return "delivered" if 200 <= response.status < 300 else "failed"
    except Exception:
        return "failed"
