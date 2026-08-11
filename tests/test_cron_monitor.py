from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core.cron_security import cron_signature
from app.main import app

PATH = "/api/v1/internal/monitor/run"
SECRET = "c" * 48


def _headers(timestamp: str, secret: str = SECRET) -> dict[str, str]:
    return {
        "X-ValuSee-Timestamp": timestamp,
        "X-ValuSee-Signature": cron_signature(secret, timestamp, "POST", PATH),
    }


def test_scheduled_monitor_accepts_valid_signature(monkeypatch):
    timestamp = str(int(time.time()))
    monkeypatch.setenv("VALUSee_CRON_SECRET", SECRET)
    calls: list[bool] = []
    monkeypatch.setattr(
        "app.api.routes.run_monitor_cycle",
        lambda: calls.append(True) or {"processed": 2, "notifications": 1},
    )

    response = TestClient(app).post(PATH, headers=_headers(timestamp))

    assert response.status_code == 200
    assert response.json()["result"] == {"processed": 2, "notifications": 1}
    assert calls == [True]


def test_scheduled_monitor_rejects_invalid_or_expired_signature(monkeypatch):
    monkeypatch.setenv("VALUSee_CRON_SECRET", SECRET)
    client = TestClient(app)

    invalid = client.post(
        PATH,
        headers={"X-ValuSee-Timestamp": str(int(time.time())), "X-ValuSee-Signature": "0" * 64},
    )
    expired_at = str(int(time.time()) - 301)
    expired = client.post(PATH, headers=_headers(expired_at))

    assert invalid.status_code == 401
    assert expired.status_code == 401


def test_scheduled_monitor_requires_server_secret(monkeypatch):
    monkeypatch.delenv("VALUSee_CRON_SECRET", raising=False)

    response = TestClient(app).post(PATH)

    assert response.status_code == 503
