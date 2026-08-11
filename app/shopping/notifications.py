from __future__ import annotations

import hashlib
import hmac
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime
from urllib.request import Request, urlopen


def deliver_notification(
    notification: dict[str, object],
    preferences: dict[str, object] | None = None,
) -> str:
    """Deliver configured channels; durable in-app storage remains canonical."""
    preferences = preferences or {}
    deliveries: list[str] = []
    if bool(preferences.get("in_app_enabled", True)):
        deliveries.append("in_app")
    quiet = _is_quiet_time(preferences)
    if not quiet and bool(preferences.get("email_enabled", True)) and _deliver_email(notification):
        deliveries.append("email")
    if quiet:
        deliveries.append("quiet_deferred")
    endpoint = os.getenv("VALUSee_NOTIFICATION_WEBHOOK_URL", "").strip()
    if not endpoint or quiet:
        return "+".join(deliveries) or "audit_only"
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
    return "+".join(deliveries) or "audit_only"


def _is_quiet_time(preferences: dict[str, object], now: datetime | None = None) -> bool:
    start = str(preferences.get("quiet_start") or "").strip()
    end = str(preferences.get("quiet_end") or "").strip()
    if not start or not end or start == end:
        return False
    try:
        current = (now or datetime.now().astimezone()).strftime("%H:%M")
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
    except ValueError:
        return False
    return start <= current < end if start < end else current >= start or current < end


def _deliver_email(notification: dict[str, object]) -> bool:
    try:
        from app.auth.service import auth_store

        user = auth_store.get_user(str(notification.get("user_id") or ""))
        recipient = str((user or {}).get("email") or "").strip()
        if not recipient:
            return False
        return send_transactional_email(recipient, str(notification.get("title") or "ValuSee 提醒"), str(notification.get("message") or ""))
    except Exception:
        return False


def send_transactional_email(recipient: str, subject: str, content: str) -> bool:
    transport = os.getenv("VALUSee_EMAIL_TRANSPORT", "smtp").strip().lower()
    if transport == "console" and os.getenv("APP_ENV", "dev").lower() not in {"prod", "production"}:
        return bool(recipient)
    host = os.getenv("VALUSee_SMTP_HOST", "").strip()
    if not host or not recipient:
        return False
    try:
        port = int(os.getenv("VALUSee_SMTP_PORT", "465"))
        username = os.getenv("VALUSee_SMTP_USERNAME", "").strip()
        password = os.getenv("VALUSee_SMTP_PASSWORD", "")
        sender = os.getenv("VALUSee_SMTP_FROM", username).strip()
        if not sender:
            return False
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient
        message.set_content(content)
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
