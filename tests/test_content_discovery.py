from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.store import ShoppingStore


def test_published_content_search_detail_and_related_are_governed():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "content.db")
        draft = store.save_content({"title": "Internal draft", "summary": "Not public", "body": "Draft", "category": "Monitor", "status": "draft"})
        first = store.save_content({"title": "USB-C monitor guide", "summary": "Power delivery explained", "body": "Check cable and wattage.", "category": "Monitor", "status": "published", "source_url": "https://source.example/guide"})
        second = store.save_content({"title": "Monitor warranty", "summary": "Dead pixel policies", "body": "Compare warranty terms.", "category": "Monitor", "status": "published"})

        assert store.get_content(draft["content_id"]) is None
        assert store.get_content(draft["content_id"], public_only=False)["status"] == "draft"
        assert [item["content_id"] for item in store.list_content(query_text="wattage")] == [first["content_id"]]
        assert store.get_content(first["content_id"])["source_url"] == "https://source.example/guide"
        assert [item["content_id"] for item in store.related_content(first["content_id"])] == [second["content_id"]]


def test_content_source_rejects_script_protocol():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "content.db")
        try:
            store.save_content({"title": "Unsafe", "summary": "Unsafe source", "source_url": "javascript:alert(1)"})
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe content source must be rejected")
