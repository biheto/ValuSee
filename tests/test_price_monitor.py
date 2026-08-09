from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

from app.shopping.store import ShoppingStore, final_price_from_breakdown


def _product(price: float = 129.0) -> dict[str, object]:
    return {
        "title": "智能保温杯",
        "platform": "JD",
        "brand": "ValueCup",
        "model": "C1",
        "price": price,
        "coupon": 0,
        "platform_discount": 0,
        "member_discount": 0,
        "subsidy": 0,
        "pay_discount": 0,
        "shipping": 0,
        "gift_value": 0,
        "official_store": True,
    }


def test_create_monitor_persists_target_price_task():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        record = store.create_monitor(
            user_id="u1",
            product=_product(),
            target_price=99,
            current_final_price=129,
            monitor_days=30,
            notify_channel="in_app",
        )

        monitors = store.list_monitors(user_id="u1")
        assert len(monitors) == 1
        assert monitors[0]["monitor_id"] == record["monitor_id"]
        assert monitors[0]["status"] == "watching"
        assert monitors[0]["target_price"] == 99


def test_price_check_updates_monitor_when_target_reached():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        record = store.create_monitor(
            user_id="u1",
            product=_product(),
            target_price=99,
            current_final_price=129,
            monitor_days=30,
            notify_channel="in_app",
        )

        breakdown = final_price_from_breakdown({"price": 129, "coupon": 40})
        check = store.record_price_check(
            monitor_id=record["monitor_id"],
            breakdown=breakdown,
            stock_status="in_stock",
            source="unit-test",
        )
        monitor = store.get_monitor(record["monitor_id"])
        checks = store.list_price_checks(record["monitor_id"])

        assert check["target_reached"] is True
        assert monitor is not None
        assert monitor["status"] == "target_reached"
        assert monitor["current_final_price"] == 89
        assert len(checks) == 1


def test_monitor_admin_actions_are_stateful_and_audited():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        record = store.create_monitor(
            user_id="u1", product=_product(), target_price=99,
            current_final_price=129, monitor_days=30, notify_channel="in_app",
        )
        paused = store.update_monitor_status(record["monitor_id"], "paused", actor_id="admin", reason="来源暂时不可用")
        assert paused and paused["status"] == "paused"
        resumed = store.update_monitor_status(record["monitor_id"], "watching", actor_id="admin", reason="已恢复")
        assert resumed and resumed["status"] == "watching"
        actions = store.list_monitor_actions(record["monitor_id"])
        assert [item["action"] for item in actions][:2] == ["watching", "paused"]


def test_monitor_invalid_transition_is_rejected():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        record = store.create_monitor(
            user_id="u1", product=_product(), target_price=99,
            current_final_price=129, monitor_days=30, notify_channel="in_app",
        )
        try:
            store.update_monitor_status(record["monitor_id"], "completed", actor_id="admin")
        except ValueError as exc:
            assert "invalid monitor transition" in str(exc)
        else:
            raise AssertionError("invalid transition should fail")
