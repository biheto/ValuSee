from __future__ import annotations

import hashlib
import hmac
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.request import Request, urlopen


def deliver_notification(notification: dict[str, object]) -> str:
    """Deliver configured channels; durable in-app storage remains canonical."""
    deliveries = ["in_app"]
    if _deliver_email(notification):
        deliveries.append("email")
    endpoint = os.getenv("VALUSee_NOTIFICATION_WEBHOOK_URL", "").strip()
    if not endpoint:
        return "+".join(deliveries)
    body = json.dumps(notification, ensure_ascii=False).encode("utf-8")
    secret = os.getenv("VALUSee_NOTIFICATION_WEBHOOK_SECRET", "").encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest() if secret else ""
    request = Request(endpoint, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ValuSee-Signature": signature,
    })
    try:
        with urlopen(request, timeout=5) as response:
            if 200 <= response.status < 300:
                deliveries.append("webhook")
    except Exception:
        pass
    return "+".join(deliveries)


def _deliver_email(notification: dict[str, object]) -> bool:
    host = os.getenv("VALUSee_SMTP_HOST", "").strip()
    if not host:
        return False
    try:
        from app.auth.service import auth_store

        user = auth_store.get_user(str(notification.get("user_id") or ""))
        recipient = str((user or {}).get("email") or "").strip()
        if not recipient:
            return False
        port = int(os.getenv("VALUSee_SMTP_PORT", "465"))
        username = os.getenv("VALUSee_SMTP_USERNAME", "").strip()
        password = os.getenv("VALUSee_SMTP_PASSWORD", "")
        sender = os.getenv("VALUSee_SMTP_FROM", username).strip()
        if not sender:
            return False
        message = EmailMessage()
        message["Subject"] = str(notification.get("title") or "ValuSee 提醒")
        message["From"] = sender
        message["To"] = recipient
        message.set_content(str(notification.get("message") or ""))
        use_ssl = os.getenv("VALUSee_SMTP_SSL", "true").lower() not in {"0", "false", "no"}
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=8, context=ssl.create_default_context()) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=8) as client:
                client.starttls(context=ssl.create_default_context())
                if username:
                    client.login(username, password)
                client.send_message(message)
        return True
    except Exception:
        return False
