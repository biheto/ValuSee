from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.store import ShoppingStore


def product(price: float = 1200) -> dict:
    return {"title": "Monitor", "url": "https://shop.example/monitor", "platform": "JD", "price": price, "brand": "Dell", "model": "U27", "sku": "U27"}


def test_monitor_preferences_budget_pools_calendar_and_ledger_are_persisted():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "savings.db")
        monitor = store.create_monitor(user_id="owner", product=product(), target_price=1000, current_final_price=1200, monitor_days=30, notify_channel="in_app")
        preference = store.save_monitor_preference("owner", monitor["monitor_id"], "Office", "weekly")
        assert preference["group_name"] == "Office"
        assert store.list_monitors("owner")[0]["frequency"] == "weekly"
        try:
            store.save_monitor_preference("other", monitor["monitor_id"], "Private", "daily")
        except ValueError:
            pass
        else:
            raise AssertionError("monitor preference must be owner scoped")

        pool = store.save_budget_pool("owner", {"name": "Desk setup", "target_amount": 5000, "spent_amount": 1200})
        assert store.list_budget_pools("owner")[0]["pool_id"] == pool["pool_id"]
        store.record_price_snapshot(user_id="owner", product=product(), final_price=1100, source="extension")
        assert store.price_calendar("owner")[0]["observations"] == 1

        purchase = store.create_purchase(user_id="owner", product=product(), paid_price=1000, platform="JD", store_name="Official", purchased_at=None, price_protection_days=7, return_days=7, warranty_months=12, consumable_cycle_days=None, notes="")
        ledger = store.list_savings("owner")
        assert ledger["total"] == 200 and ledger["items"][0]["source_id"] == purchase["purchase_id"]
        assert store.list_savings("other")["items"] == []
