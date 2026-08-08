from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.store import ShoppingStore


def test_purchase_record_generates_after_sales_reminders():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        record = store.create_purchase(
            user_id="u1",
            product={
                "title": "智能保温杯",
                "platform": "JD",
                "brand": "ValueCup",
                "model": "C1",
            },
            paid_price=89,
            platform="JD",
            store_name="官方旗舰店",
            purchased_at="2026-08-08T00:00:00Z",
            price_protection_days=7,
            return_days=7,
            warranty_months=12,
            consumable_cycle_days=180,
            notes="测试购买记录",
        )
        purchases = store.list_purchases(user_id="u1")

        assert record["price_protection_deadline"] == "2026-08-15T00:00:00Z"
        assert record["return_deadline"] == "2026-08-15T00:00:00Z"
        assert record["warranty_deadline"] == "2027-08-03T00:00:00Z"
        assert record["consumable_reminder_at"] == "2027-02-04T00:00:00Z"
        assert len(record["reminders"]) == 4
        assert len(purchases) == 1
        assert purchases[0]["purchase_id"] == record["purchase_id"]
