from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.harness.events import utc_now_iso


class ShoppingStore:
    def __init__(self, db_path: str | Path = "data/valuesee.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shopping_price_monitor (
                    monitor_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    current_final_price REAL NOT NULL,
                    product_json TEXT NOT NULL,
                    notify_channel TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shopping_price_check (
                    check_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    price REAL NOT NULL,
                    final_price REAL NOT NULL,
                    breakdown_json TEXT NOT NULL,
                    stock_status TEXT NOT NULL,
                    target_reached INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create_monitor(
        self,
        *,
        user_id: str,
        product: dict[str, Any],
        target_price: float,
        current_final_price: float,
        monitor_days: int,
        notify_channel: str,
    ) -> dict[str, Any]:
        monitor_id = f"mon_{uuid4().hex}"
        now = utc_now_iso()
        expires_at = _utc_plus_days(monitor_days)
        message = _monitor_message(current_final_price, target_price)
        record = {
            "monitor_id": monitor_id,
            "user_id": user_id,
            "status": "target_reached" if current_final_price <= target_price else "watching",
            "target_price": round(target_price, 2),
            "current_final_price": round(current_final_price, 2),
            "product": product,
            "notify_channel": notify_channel,
            "created_at": now,
            "expires_at": expires_at,
            "updated_at": now,
            "last_message": message,
        }
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO shopping_price_monitor(
                    monitor_id, user_id, status, target_price, current_final_price,
                    product_json, notify_channel, created_at, expires_at, updated_at, last_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["monitor_id"],
                    record["user_id"],
                    record["status"],
                    record["target_price"],
                    record["current_final_price"],
                    json.dumps(product, ensure_ascii=False),
                    record["notify_channel"],
                    record["created_at"],
                    record["expires_at"],
                    record["updated_at"],
                    record["last_message"],
                ),
            )
        return record

    def list_monitors(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT monitor_id, user_id, status, target_price, current_final_price,
                   product_json, notify_channel, created_at, expires_at, updated_at, last_message
            FROM shopping_price_monitor
        """
        params: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at DESC"
        with self._session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_monitor(row) for row in rows]

    def get_monitor(self, monitor_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute(
                """
                SELECT monitor_id, user_id, status, target_price, current_final_price,
                       product_json, notify_channel, created_at, expires_at, updated_at, last_message
                FROM shopping_price_monitor
                WHERE monitor_id = ?
                """,
                (monitor_id,),
            ).fetchone()
        return _row_to_monitor(row) if row else None

    def record_price_check(
        self,
        *,
        monitor_id: str,
        breakdown: dict[str, Any],
        stock_status: str,
        source: str,
    ) -> dict[str, Any]:
        monitor = self.get_monitor(monitor_id)
        if not monitor:
            raise KeyError(monitor_id)
        final_price = float(breakdown["final_price"])
        target_reached = final_price <= float(monitor["target_price"])
        status = "target_reached" if target_reached else "watching"
        message = _monitor_message(final_price, float(monitor["target_price"]))
        now = utc_now_iso()
        check = {
            "check_id": f"chk_{uuid4().hex}",
            "monitor_id": monitor_id,
            "source": source,
            "price": float(breakdown["page_price"]),
            "final_price": round(final_price, 2),
            "breakdown": breakdown,
            "stock_status": stock_status,
            "target_reached": target_reached,
            "message": message,
            "created_at": now,
        }
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO shopping_price_check(
                    check_id, monitor_id, source, price, final_price, breakdown_json,
                    stock_status, target_reached, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    check["check_id"],
                    monitor_id,
                    source,
                    check["price"],
                    check["final_price"],
                    json.dumps(breakdown, ensure_ascii=False),
                    stock_status,
                    1 if target_reached else 0,
                    message,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE shopping_price_monitor
                SET status = ?, current_final_price = ?, updated_at = ?, last_message = ?
                WHERE monitor_id = ?
                """,
                (status, check["final_price"], now, message, monitor_id),
            )
        return check

    def list_price_checks(self, monitor_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT check_id, monitor_id, source, price, final_price, breakdown_json,
                       stock_status, target_reached, message, created_at
                FROM shopping_price_check
                WHERE monitor_id = ?
                ORDER BY created_at DESC
                """,
                (monitor_id,),
            ).fetchall()
        return [_row_to_check(row) for row in rows]


def final_price_from_breakdown(payload: dict[str, Any]) -> dict[str, float]:
    page_price = float(payload.get("price") or 0.0)
    coupon = float(payload.get("coupon") or 0.0)
    platform_discount = float(payload.get("platform_discount") or 0.0)
    member_discount = float(payload.get("member_discount") or 0.0)
    subsidy = float(payload.get("subsidy") or 0.0)
    pay_discount = float(payload.get("pay_discount") or 0.0)
    shipping = float(payload.get("shipping") or 0.0)
    gift_value = float(payload.get("gift_value") or 0.0)
    final_price = max(0.0, page_price - coupon - platform_discount - member_discount - subsidy - pay_discount + shipping - gift_value)
    return {
        "page_price": round(page_price, 2),
        "coupon": round(coupon, 2),
        "platform_discount": round(platform_discount, 2),
        "member_discount": round(member_discount, 2),
        "subsidy": round(subsidy, 2),
        "pay_discount": round(pay_discount, 2),
        "shipping": round(shipping, 2),
        "gift_value": round(gift_value, 2),
        "final_price": round(final_price, 2),
    }


def _row_to_monitor(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "monitor_id": row["monitor_id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "target_price": float(row["target_price"]),
        "current_final_price": float(row["current_final_price"]),
        "product": json.loads(row["product_json"]),
        "notify_channel": row["notify_channel"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "updated_at": row["updated_at"],
        "last_message": row["last_message"] or "",
    }


def _row_to_check(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "check_id": row["check_id"],
        "monitor_id": row["monitor_id"],
        "source": row["source"],
        "price": float(row["price"]),
        "final_price": float(row["final_price"]),
        "breakdown": json.loads(row["breakdown_json"]),
        "stock_status": row["stock_status"],
        "target_reached": bool(row["target_reached"]),
        "message": row["message"],
        "created_at": row["created_at"],
    }


def _utc_plus_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _monitor_message(final_price: float, target_price: float) -> str:
    if final_price <= target_price:
        return f"已达到目标价：当前到手价 {final_price:.0f} 元，目标价 {target_price:.0f} 元。"
    return f"继续观察：当前到手价 {final_price:.0f} 元，距离目标价还差 {final_price - target_price:.0f} 元。"


shopping_store = ShoppingStore()
