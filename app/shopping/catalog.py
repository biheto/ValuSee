from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.core.database import connect_database
from app.harness.events import utc_now_iso


class CommerceCatalog:
    """Admin-owned canonical product/SKU records used to stabilize matching."""

    def __init__(self, db_path: str | Path = "data/valuesee.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS commerce_catalog_product(
                product_id TEXT PRIMARY KEY, brand TEXT NOT NULL, model TEXT NOT NULL,
                category TEXT NOT NULL, title TEXT NOT NULL, specs_json TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS commerce_catalog_sku(
                sku_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, sku TEXT NOT NULL,
                variant TEXT NOT NULL, specs_json TEXT NOT NULL, source_url TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(product_id, sku)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_sku_product ON commerce_catalog_sku(product_id)")

    def _connect(self):
        return connect_database(self.db_path)

    @contextmanager
    def _session(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _product(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["specs"] = json.loads(item.pop("specs_json") or "{}")
        return item

    @staticmethod
    def _sku(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["specs"] = json.loads(item.pop("specs_json") or "{}")
        return item

    def list_products(self, query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM commerce_catalog_product"
        params: list[Any] = []
        if query:
            sql += " WHERE brand LIKE ? OR model LIKE ? OR title LIKE ?"
            term = f"%{query}%"
            params.extend([term, term, term])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._session() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            products = [self._product(row) for row in rows]
            for product in products:
                product["skus"] = [self._sku(row) for row in conn.execute("SELECT * FROM commerce_catalog_sku WHERE product_id=? ORDER BY updated_at DESC", (product["product_id"],)).fetchall()]
            return products

    def upsert_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        product_id = str(payload.get("product_id") or f"cat_{uuid4().hex}")
        record = (product_id, str(payload.get("brand") or "").strip(), str(payload.get("model") or "").strip(), str(payload.get("category") or "other").strip(), str(payload.get("title") or "").strip(), json.dumps(payload.get("specs") or {}, ensure_ascii=False), str(payload.get("status") or "active"), now, now)
        if not record[1] or not record[2] or not record[4]:
            raise ValueError("brand, model and title are required")
        with self._session() as conn:
            existing = conn.execute("SELECT created_at FROM commerce_catalog_product WHERE product_id=?", (product_id,)).fetchone()
            created = existing["created_at"] if existing else now
            conn.execute(
                """INSERT INTO commerce_catalog_product(product_id,brand,model,category,title,specs_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET brand=excluded.brand, model=excluded.model,
                category=excluded.category, title=excluded.title, specs_json=excluded.specs_json, status=excluded.status, updated_at=excluded.updated_at""",
                (*record[:7], created, now),
            )
        return next(item for item in self.list_products() if item["product_id"] == product_id)

    def delete_product(self, product_id: str) -> bool:
        with self._session() as conn:
            found = conn.execute("SELECT 1 FROM commerce_catalog_product WHERE product_id=?", (product_id,)).fetchone()
            if not found:
                return False
            conn.execute("DELETE FROM commerce_catalog_sku WHERE product_id=?", (product_id,))
            conn.execute("DELETE FROM commerce_catalog_product WHERE product_id=?", (product_id,))
            return True

    def upsert_sku(self, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = str(payload.get("product_id") or "").strip()
        sku = str(payload.get("sku") or "").strip()
        if not product_id or not sku:
            raise ValueError("product_id and sku are required")
        now = utc_now_iso()
        record = (str(payload.get("sku_id") or f"sku_{uuid4().hex}"), product_id, sku, str(payload.get("variant") or "").strip(), json.dumps(payload.get("specs") or {}, ensure_ascii=False), str(payload.get("source_url") or "").strip() or None, str(payload.get("status") or "active"), now, now)
        with self._session() as conn:
            if not conn.execute("SELECT 1 FROM commerce_catalog_product WHERE product_id=?", (product_id,)).fetchone():
                raise ValueError("product_id not found")
            old = conn.execute("SELECT created_at FROM commerce_catalog_sku WHERE sku_id=?", (record[0],)).fetchone()
            conn.execute(
                """INSERT INTO commerce_catalog_sku(sku_id,product_id,sku,variant,specs_json,source_url,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(sku_id) DO UPDATE SET product_id=excluded.product_id, sku=excluded.sku,
                variant=excluded.variant, specs_json=excluded.specs_json, source_url=excluded.source_url, status=excluded.status,
                updated_at=excluded.updated_at""",
                (*record[:7], old["created_at"] if old else now, now),
            )
            row = conn.execute("SELECT * FROM commerce_catalog_sku WHERE sku_id=?", (record[0],)).fetchone()
            return self._sku(row)

    def delete_sku(self, sku_id: str) -> bool:
        with self._session() as conn:
            cursor = conn.execute("DELETE FROM commerce_catalog_sku WHERE sku_id=?", (sku_id,))
            return cursor.rowcount > 0


commerce_catalog = CommerceCatalog()
