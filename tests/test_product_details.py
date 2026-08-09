from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.store import ShoppingStore


def product(url: str, sku: str, *, platform: str = "JD", price: float = 1499) -> dict:
    return {
        "title": f"Dell U2723 {sku}",
        "platform": platform,
        "url": url,
        "brand": "Dell",
        "model": "U2723QE",
        "sku": sku,
        "specs": {"size": "27 inch", "power": "90W"},
        "price": price,
        "coupon": 0,
        "platform_discount": 0,
        "member_discount": 0,
        "subsidy": 0,
        "pay_discount": 0,
        "shipping": 0,
        "gift_value": 0,
        "condition": "new",
        "official_store": True,
        "return_days": 7,
        "warranty_months": 36,
        "notes": "Captured from a user-provided source.",
    }


def test_product_detail_aggregates_only_persisted_owner_evidence():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "products.db")
        primary = product("https://shop.example/product/1", "U2723QE", price=1499)
        same_sku = product("https://other.example/item/88", "U2723QE", platform="Tmall", price=1459)
        alternative = product("https://shop.example/product/2", "U2723QX", price=1299)
        product_ref = store.upsert_product_record("owner", primary)
        assert product_ref == store.upsert_product_record("owner", primary)
        store.upsert_product_record("owner", same_sku)
        store.upsert_product_record("owner", alternative)
        store.upsert_product_record("other-user", product("https://private.example/item", "U2723QE", price=999))
        store.record_price_snapshot(user_id="owner", product=primary, final_price=1399, source="extension")
        store.save_review_report(
            "owner",
            primary,
            {"risk_level": "medium", "confidence": 0.7, "summary": "One sourced issue", "sample_size": 1, "issue_groups": []},
            ["user-import"],
        )

        detail = store.product_detail("owner", product_ref)
        assert detail and detail["product"]["url"] == primary["url"]
        assert [item["url"] for item in detail["offers"]] == [same_sku["url"]]
        assert [item["url"] for item in detail["alternatives"]] == [alternative["url"]]
        assert detail["price_history"]["snapshots"][0]["final_price"] == 1399
        assert detail["review_evidence"]["sources"] == ["user-import"]
        assert all(item["url"] != "https://private.example/item" for item in detail["offers"])
        assert store.product_detail("other-user", product_ref) is None


def test_saved_product_returns_stable_detail_reference():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "products.db")
        item = product("https://shop.example/product/1", "U2723QE")
        saved = store.save_item("owner", "favorite", item["url"], item["title"], item)
        assert saved["product_ref"].startswith("prd_")
        assert store.product_detail("owner", saved["product_ref"])["product"] == item
