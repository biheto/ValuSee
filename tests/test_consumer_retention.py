from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.store import ShoppingStore


def test_saved_groups_search_and_bulk_actions_are_owner_scoped():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "retention.db")
        first = store.save_item("owner", "favorite", "https://shop.example/1", "Dell monitor", {"title": "Dell monitor", "url": "https://shop.example/1", "brand": "Dell"})
        second = store.save_item("owner", "favorite", "https://shop.example/2", "Sony headset", {"title": "Sony headset", "url": "https://shop.example/2", "brand": "Sony"})
        foreign = store.save_item("other", "favorite", "https://shop.example/3", "Private", {"title": "Private", "url": "https://shop.example/3"})
        group = store.save_saved_group("owner", "Office")

        assert store.bulk_saved_items("owner", [first["saved_id"], foreign["saved_id"]], "move", group["group_id"]) == 1
        grouped = store.list_saved_items("owner", group_id=group["group_id"])
        assert grouped[0]["saved_id"] == first["saved_id"] and grouped[0]["group_name"] == "Office"
        assert [item["saved_id"] for item in store.list_saved_items("owner", query_text="Sony")] == [second["saved_id"]]
        assert store.bulk_saved_items("owner", [first["saved_id"], foreign["saved_id"]], "delete") == 1
        assert store.list_saved_items("other")[0]["saved_id"] == foreign["saved_id"]


def test_notification_delivery_retry_and_delete_are_audited_and_scoped():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "retention.db")
        notification = store.create_notification(user_id="owner", kind="price_reached", title="Target reached", message="Now 999", idempotency_key="target:1")
        assert notification
        listed = store.list_notifications("owner")
        assert listed[0]["delivery"]["attempt"] == 1
        assert listed[0]["target_url"] == "/?view=monitors"
        retried = store.retry_notification("owner", notification["notification_id"])
        assert retried and retried["attempt"] == 2
        assert store.retry_notification("other", notification["notification_id"]) is None
        assert store.delete_notifications("other", [notification["notification_id"]]) == 0
        assert store.delete_notifications("owner", [notification["notification_id"]]) == 1
        assert store.list_notifications("owner") == []
