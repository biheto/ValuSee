from pathlib import Path
from tempfile import TemporaryDirectory

from app.shopping.catalog import CommerceCatalog


def test_catalog_product_and_sku_crud():
    with TemporaryDirectory() as tmp:
        catalog = CommerceCatalog(Path(tmp) / "catalog.db")
        product = catalog.upsert_product({"brand": "Apple", "model": "A", "title": "耳机", "category": "headphones", "specs": {"port": "USB-C"}})
        sku = catalog.upsert_sku({"product_id": product["product_id"], "sku": "A-USBC", "variant": "USB-C", "specs": {"generation": 2}})
        listed = catalog.list_products(query="A")
        assert listed[0]["product_id"] == product["product_id"]
        assert listed[0]["skus"][0]["sku"] == "A-USBC"
        assert catalog.delete_sku(sku["sku_id"])
        assert catalog.delete_product(product["product_id"])
        assert catalog.list_products() == []
