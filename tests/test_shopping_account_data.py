from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore
from app.shopping.store import ShoppingStore


def _product(title: str = "Test monitor") -> dict[str, object]:
    return {"title": title, "platform": "JD", "price": 100.0, "model": "T1"}


def test_profile_comparison_report_and_feedback_are_isolated():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        store.save_profile("u1", {"budget": 3000, "brands": ["A"]})
        store.save_profile("u2", {"budget": 1000})
        comparison = store.save_comparison("u1", "Office setup", [_product()])
        store.save_report("u1", "task-1", "Choose a monitor", [_product()], {"recommendation": "buy"})
        store.create_feedback("u1", {"feedback_type": "wrong_price", "content": "Coupon expired"})

        assert store.get_profile("u1")["profile"]["budget"] == 3000
        assert store.list_comparisons("u2") == []
        assert "products_json" not in store.list_comparisons("u1")[0]
        assert "result_json" not in store.list_reports("u1")[0]
        assert "evidence_json" not in store.list_feedback("u1")[0]

        try:
            store.save_comparison("u2", "Hijack", [], comparison["comparison_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("another user must not update a comparison")
        assert store.list_comparisons("u1")[0]["name"] == "Office setup"


def test_comparison_update_delete_and_notification_preferences():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        comparison = store.save_comparison("u1", "First", [_product()])
        updated = store.save_comparison("u1", "Updated", [_product("Second")], comparison["comparison_id"])
        preferences = store.save_notification_preference(
            "u1", {"email_enabled": False, "in_app_enabled": True, "quiet_start": "22:00", "quiet_end": "08:00"}
        )

        assert updated["name"] == "Updated"
        assert store.get_notification_preference("u1") == preferences
        assert store.delete_comparison("u2", comparison["comparison_id"]) is False
        assert store.delete_comparison("u1", comparison["comparison_id"]) is True


def test_monitor_update_and_delete_require_owner():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        monitor = store.create_monitor(
            user_id="u1", product=_product(), target_price=80,
            current_final_price=100, monitor_days=30, notify_channel="in_app",
        )

        assert store.update_user_monitor("u2", monitor["monitor_id"], target_price=70) is None
        updated = store.update_user_monitor("u1", monitor["monitor_id"], target_price=75, status="paused")
        assert updated and updated["target_price"] == 75 and updated["status"] == "paused"
        assert store.delete_user_monitor("u2", monitor["monitor_id"]) is False
        assert store.delete_user_monitor("u1", monitor["monitor_id"]) is True


def test_account_export_and_delete_cover_shopping_account_tables():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "account.db"
        shopping = ShoppingStore(path)
        auth = AuthStore(path)
        user = auth.register("buyer@example.com", "password-123", "Buyer")
        user_id = user["user_id"]
        shopping.save_profile(user_id, {"budget": 2000})
        shopping.save_comparison(user_id, "Saved", [_product()])
        shopping.save_report(user_id, "task-1", "Goal", [_product()], {"score": 88})
        shopping.create_feedback(user_id, {"content": "Needs correction"})
        shopping.save_notification_preference(user_id, {"email_enabled": False})

        exported = auth.export_account(user_id)
        assert exported["profile"] and exported["comparisons"] and exported["reports"]
        assert exported["feedback"] and exported["notification_preferences"]

        auth.delete_account(user_id)
        assert auth.get_user(user_id) is None
        assert shopping.get_profile(user_id)["profile"] == {}
        assert shopping.list_comparisons(user_id) == []
        assert shopping.list_reports(user_id) == []


def test_feedback_has_a_governed_resolution_lifecycle():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        feedback = store.create_feedback("u1", {"feedback_type": "wrong_sku", "content": "Wrong generation"})
        reviewing = store.update_feedback_status(feedback["feedback_id"], "reviewing")
        resolved = store.update_feedback_status(feedback["feedback_id"], "resolved")
        assert reviewing and reviewing["status"] == "reviewing"
        assert resolved and resolved["status"] == "resolved"


def test_business_metrics_track_savings_and_quality_events():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        store.record_business_event("u1", "analysis_started", "task-1", idempotency_key="start-1")
        store.record_business_event("u1", "analysis_completed", "task-1", metadata={"latency_ms": 120}, idempotency_key="done-1")
        store.record_business_event("u1", "recommendation_accepted", "task-1", idempotency_key="accept-1")
        store.record_business_event("u1", "monitor_created", "mon-1", idempotency_key="monitor-1")
        store.record_business_event("u1", "monitor_target_reached", "mon-1", idempotency_key="target-1")
        store.record_business_event("u1", "purchase_confirmed", "buy-1", value=88, idempotency_key="purchase-1")
        metrics = store.business_metrics()
        assert metrics["analysis_completion_rate"] == 1.0
        assert metrics["recommendation_acceptance_rate"] == 1.0
        assert metrics["monitor_conversion_rate"] == 1.0
        assert metrics["actual_savings"] == 88
        assert metrics["analysis_p95_latency_ms"] == 120


def test_saved_items_dashboard_and_message_state_are_account_scoped():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        product = _product("Saved monitor")
        favorite = store.save_item("u1", "favorite", "https://shop.example/item", "Saved monitor", product)
        store.save_item("u1", "recent", "https://shop.example/item", "Saved monitor", product)
        store.save_item("u1", "brand", "ValueCup", "ValueCup")
        store.create_notification(user_id="u1", kind="price", title="Price changed", message="Now lower", idempotency_key="message-1")

        dashboard = store.user_dashboard("u1")
        assert dashboard["favorite"] == 1 and dashboard["recent"] == 1 and dashboard["brand"] == 1
        assert dashboard["unread"] == 1
        assert store.list_saved_items("u2") == []
        assert store.delete_saved_item("u2", favorite["saved_id"]) is False
        assert store.mark_notification_read("u2") == 0
        assert store.mark_notification_read("u1") == 1
        assert store.user_dashboard("u1")["unread"] == 0


def test_purchase_status_update_requires_owner():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "shopping.db")
        purchase = store.create_purchase(
            user_id="u1", product=_product(), paid_price=90, platform="manual", store_name="Store",
            purchased_at=None, price_protection_days=7, return_days=7, warranty_months=12,
            consumable_cycle_days=None, notes="",
        )
        assert store.update_purchase("u2", purchase["purchase_id"], {"status": "received"}) is None
        updated = store.update_purchase("u1", purchase["purchase_id"], {"status": "received", "notes": "Delivered"})
        assert updated and updated["status"] == "received" and updated["notes"] == "Delivered"
