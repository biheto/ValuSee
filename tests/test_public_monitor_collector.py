from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.monitor_collector import collect_public_monitor_updates
from app.shopping.store import ShoppingStore


def product() -> dict[str, object]:
    return {
        "title": "测试耳机", "platform": "京东", "url": "https://item.jd.com/10001.html",
        "sku": "HEADSET-1", "price": 999, "coupon": 0, "region": "北京",
        "membership": "unknown", "observation_status": "confirmed",
    }


def test_public_monitor_change_requires_confirmation_before_price_history() -> None:
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "monitor.db")
        monitor = store.create_monitor(
            user_id="owner", product=product(), target_price=899, current_final_price=999,
            monitor_days=30, notify_channel="in_app",
        )
        now = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
        result = collect_public_monitor_updates(
            store,
            fetcher=lambda _url: {
                **product(), "price": 859, "fetch_status": "parsed", "cached": False,
                "evidence": {"type": "public_html"}, "notes": "public observation",
            },
            now=now,
        )

        assert result == {"public_checked": 1, "pending_confirmations": 1, "recapture_reminders": 0}
        assert store.price_history(str(product()["url"]), user_id="owner")["count"] == 0
        captures = store.list_extension_captures("owner")
        assert captures[0]["status"] == "pending_confirmation"
        assert captures[0]["source"] == "public_monitor_refresh"
        assert store.get_monitor(monitor["monitor_id"])["status"] == "watching"
        assert "尚未核对" in store.list_notifications("owner")[0]["message"]

        not_due = collect_public_monitor_updates(
            store,
            fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("must not fetch before interval")),
            now=now + timedelta(hours=1),
        )
        assert not_due["public_checked"] == 0


def test_blocked_monitor_page_creates_extension_recapture_reminder() -> None:
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "monitor.db")
        store.create_monitor(
            user_id="owner", product=product(), target_price=899, current_final_price=999,
            monitor_days=30, notify_channel="in_app",
        )
        result = collect_public_monitor_updates(
            store,
            fetcher=lambda _url: {"fetch_status": "blocked", "price": 0, "notes": "captcha"},
            now=datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        assert result["recapture_reminders"] == 1
        assert store.list_extension_captures("owner") == []
        assert store.list_notifications("owner")[0]["kind"] == "recapture_required"
