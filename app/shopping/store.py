from __future__ import annotations

import json
import hashlib
import ipaddress
import re
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from app.harness.events import utc_now_iso
from app.auth.service import decrypt_user_secret, encrypt_user_secret
from app.core.database import connect_database, is_integrity_error
from app.core.paths import resolve_runtime_path
from app.shopping.notifications import deliver_notification


class ShoppingStore:
    def __init__(self, db_path: str | Path = "data/valuesee.db"):
        self.db_path = resolve_runtime_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._risk_rules_lock = threading.Lock()
        self._risk_rule_buffers: list[tuple[dict[str, Any], ...]] = [tuple(), tuple()]
        self._active_risk_rule_buffer = 0
        self.reload_risk_rule_snapshot()

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shopping_purchase_record (
                    purchase_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    product_json TEXT NOT NULL,
                    paid_price REAL NOT NULL,
                    platform TEXT,
                    store_name TEXT,
                    purchased_at TEXT NOT NULL,
                    price_protection_deadline TEXT,
                    return_deadline TEXT,
                    warranty_deadline TEXT,
                    consumable_reminder_at TEXT,
                    status TEXT NOT NULL,
                    reminders_json TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_purchase_attachment(
                attachment_id TEXT PRIMARY KEY,purchase_id TEXT NOT NULL,user_id TEXT NOT NULL,
                attachment_type TEXT NOT NULL,original_name TEXT NOT NULL,content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,storage_backend TEXT NOT NULL,
                storage_key TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_attachment_owner ON shopping_purchase_attachment(user_id,purchase_id,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_price_protection_claim(
                claim_id TEXT PRIMARY KEY,purchase_id TEXT NOT NULL,user_id TEXT NOT NULL,status TEXT NOT NULL,
                requested_amount REAL NOT NULL,approved_amount REAL NOT NULL,evidence_source TEXT NOT NULL,
                notes TEXT NOT NULL,submitted_at TEXT NOT NULL,resolved_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_protection_owner ON shopping_price_protection_claim(user_id,purchase_id,updated_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_support_ticket(
                ticket_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,purchase_id TEXT,category TEXT NOT NULL,
                subject TEXT NOT NULL,status TEXT NOT NULL,priority TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_support_message(
                message_id TEXT PRIMARY KEY,ticket_id TEXT NOT NULL,actor_id TEXT NOT NULL,actor_role TEXT NOT NULL,
                content TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_support_ticket_owner ON shopping_support_ticket(user_id,updated_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_support_case(
                ticket_id TEXT PRIMARY KEY,assigned_to TEXT,sla_due_at TEXT NOT NULL,first_response_at TEXT,
                closed_at TEXT,satisfaction INTEGER,satisfaction_note TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_campaign(
                campaign_id TEXT PRIMARY KEY,name TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,
                placement TEXT NOT NULL,target_url TEXT,status TEXT NOT NULL,starts_at TEXT,ends_at TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_risk_rule(
                rule_id TEXT PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,field_name TEXT NOT NULL,
                pattern TEXT NOT NULL,severity TEXT NOT NULL,action TEXT NOT NULL,enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_admin_audit(
                audit_id TEXT PRIMARY KEY,actor_id TEXT NOT NULL,action TEXT NOT NULL,target_type TEXT NOT NULL,
                target_id TEXT,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_experiment(
                experiment_id TEXT PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,
                variants_json TEXT NOT NULL,status TEXT NOT NULL,starts_at TEXT,ends_at TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_experiment_assignment(
                experiment_id TEXT NOT NULL,user_id TEXT NOT NULL,variant TEXT NOT NULL,created_at TEXT NOT NULL,
                PRIMARY KEY(experiment_id,user_id)
            )""")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shopping_extension_capture (
                    capture_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    product_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shopping_price_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    product_url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    final_price REAL NOT NULL,
                    region TEXT NOT NULL,
                    membership TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_snapshot_url_time ON shopping_price_snapshot(product_url, captured_at)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS shopping_notification(
                    notification_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,
                    title TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,read_at TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS shopping_monitor_action(
                    action_id TEXT PRIMARY KEY,
                    monitor_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_action_monitor ON shopping_monitor_action(monitor_id, created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_user_profile(
                user_id TEXT PRIMARY KEY,profile_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_llm_user_config(
                user_id TEXT PRIMARY KEY,api_key_encrypted TEXT NOT NULL,base_url TEXT NOT NULL,
                model TEXT NOT NULL,vision_model TEXT NOT NULL,wire_api TEXT NOT NULL,enabled INTEGER NOT NULL,
                last_test_status TEXT,last_test_at TEXT,last_test_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_comparison_list(
                comparison_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,products_json TEXT NOT NULL,
                status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_decision_report(
                report_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,task_id TEXT NOT NULL,goal TEXT NOT NULL,
                products_json TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_feedback(
                feedback_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,feedback_type TEXT NOT NULL,target_type TEXT NOT NULL,
                target_id TEXT,content TEXT NOT NULL,evidence_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_notification_preference(
                user_id TEXT PRIMARY KEY,email_enabled INTEGER NOT NULL,in_app_enabled INTEGER NOT NULL,
                quiet_start TEXT,quiet_end TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_business_event(
                event_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,event_type TEXT NOT NULL,reference_id TEXT,
                value REAL NOT NULL,metadata_json TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_business_event_type_time ON shopping_business_event(event_type,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_saved_item(
                saved_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,item_type TEXT NOT NULL,reference_key TEXT NOT NULL,
                label TEXT NOT NULL,product_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(user_id,item_type,reference_key)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_item_user_type ON shopping_saved_item(user_id,item_type,updated_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_saved_group(
                group_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(user_id,name)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_saved_group_item(
                user_id TEXT NOT NULL,saved_id TEXT NOT NULL,group_id TEXT NOT NULL,created_at TEXT NOT NULL,
                PRIMARY KEY(user_id,saved_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_notification_delivery(
                delivery_id TEXT PRIMARY KEY,notification_id TEXT NOT NULL,user_id TEXT NOT NULL,attempt INTEGER NOT NULL,
                status TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_delivery ON shopping_notification_delivery(user_id,notification_id,attempt)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_monitor_preference(
                monitor_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,group_name TEXT NOT NULL,frequency TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_monitor_poll(
                monitor_id TEXT PRIMARY KEY,checked_at TEXT NOT NULL,status TEXT NOT NULL,
                observed_price REAL NOT NULL,message TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_budget_pool(
                pool_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,target_amount REAL NOT NULL,
                spent_amount REAL NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_savings_ledger(
                entry_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_type TEXT NOT NULL,source_id TEXT NOT NULL,
                amount REAL NOT NULL,title TEXT NOT NULL,occurred_at TEXT NOT NULL,created_at TEXT NOT NULL,
                UNIQUE(user_id,source_type,source_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_content(
                content_id TEXT PRIMARY KEY,content_type TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,
                body TEXT NOT NULL,category TEXT NOT NULL,source_url TEXT,status TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,published_at TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shopping_content_status ON shopping_content(status,updated_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_share(
                share_id TEXT PRIMARY KEY,share_token TEXT NOT NULL UNIQUE,user_id TEXT NOT NULL,share_type TEXT NOT NULL,
                title TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,revoked_at TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shopping_share_owner ON shopping_share(user_id,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_product_record(
                product_ref TEXT NOT NULL,user_id TEXT NOT NULL,canonical_key TEXT NOT NULL,family_key TEXT NOT NULL,
                product_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                PRIMARY KEY(product_ref,user_id)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_product_record_family ON shopping_product_record(user_id,family_key,updated_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_product_version(
                version_id TEXT PRIMARY KEY,product_ref TEXT NOT NULL,user_id TEXT NOT NULL,version INTEGER NOT NULL,
                product_json TEXT NOT NULL,source TEXT NOT NULL,source_confidence REAL NOT NULL,created_at TEXT NOT NULL,
                UNIQUE(product_ref,user_id,version)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_price_anomaly(
                anomaly_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL UNIQUE,user_id TEXT NOT NULL,product_url TEXT NOT NULL,
                observed_price REAL NOT NULL,baseline_price REAL NOT NULL,deviation_ratio REAL NOT NULL,source TEXT NOT NULL,
                source_confidence REAL NOT NULL,status TEXT NOT NULL,reviewed_by TEXT,review_note TEXT NOT NULL,
                created_at TEXT NOT NULL,reviewed_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS shopping_review_report(
                report_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,product_ref TEXT NOT NULL,product_json TEXT NOT NULL,
                report_json TEXT NOT NULL,sources_json TEXT NOT NULL,created_at TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_report_product ON shopping_review_report(user_id,product_ref,created_at)")

    def create_extension_capture(
        self,
        *,
        user_id: str,
        product: dict[str, Any],
        source: str,
        captured_at: str | None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        record = {
            "capture_id": f"cap_{uuid4().hex}",
            "user_id": user_id,
            "status": "pending_confirmation",
            "product": product,
            "source": source,
            "captured_at": captured_at or now,
            "created_at": now,
        }
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO shopping_extension_capture(
                    capture_id, user_id, status, product_json, source, captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["capture_id"], record["user_id"], record["status"],
                    json.dumps(product, ensure_ascii=False), record["source"],
                    record["captured_at"], record["created_at"],
                ),
            )
        return record

    def list_extension_captures(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM shopping_extension_capture"
        params: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at DESC LIMIT 100"
        with self._session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "capture_id": row["capture_id"], "user_id": row["user_id"],
                "status": row["status"], "product": json.loads(row["product_json"]),
                "source": row["source"], "captured_at": row["captured_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def confirm_extension_capture(self, capture_id: str, user_id: str | None = None, product: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._session() as conn:
            query = "SELECT * FROM shopping_extension_capture WHERE capture_id=?"
            params: tuple[Any, ...] = (capture_id,)
            if user_id:
                query += " AND user_id=?"
                params = (capture_id, user_id)
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            confirmed_now = row["status"] == "pending_confirmation"
            if confirmed_now:
                stored_product = product or json.loads(row["product_json"])
                stored_product["observation_status"] = "confirmed"
                conn.execute(
                    "UPDATE shopping_extension_capture SET status='imported',product_json=? WHERE capture_id=?",
                    (json.dumps(stored_product, ensure_ascii=False), capture_id),
                )
                row = conn.execute("SELECT * FROM shopping_extension_capture WHERE capture_id=?", (capture_id,)).fetchone()
        return {
            "capture_id": row["capture_id"], "user_id": row["user_id"],
            "status": row["status"], "product": json.loads(row["product_json"]),
            "source": row["source"], "captured_at": row["captured_at"],
            "created_at": row["created_at"],
            "confirmed_now": confirmed_now,
        }

    def record_price_snapshot(
        self,
        *,
        user_id: str,
        product: dict[str, Any],
        final_price: float,
        source: str,
        captured_at: str | None = None,
        region: str = "unknown",
        membership: str = "unknown",
    ) -> dict[str, Any]:
        record = {
            "snapshot_id": f"price_{uuid4().hex}", "user_id": user_id,
            "product_url": str(product.get("url", "")), "platform": str(product.get("platform", "")),
            "title": str(product.get("title", "")), "price": float(product.get("price", 0)),
            "final_price": round(float(final_price), 2), "region": region, "membership": membership,
            "conditions": {
                key: float(product.get(key, 0) or 0)
                for key in ("coupon", "platform_discount", "member_discount", "subsidy", "pay_discount", "shipping", "gift_value")
            } | {
                "sku": str(product.get("sku", "")),
                "selected_variant": str(product.get("selected_variant", "")),
                "confirmation_status": str(product.get("observation_status", "requires_confirmation")),
                "evidence": product.get("evidence") if isinstance(product.get("evidence"), dict) else {},
            },
            "source": source, "captured_at": captured_at or utc_now_iso(),
        }
        with self._session() as conn:
            prior = [float(row["final_price"]) for row in conn.execute("SELECT final_price FROM shopping_price_snapshot WHERE user_id=? AND product_url=? AND final_price>0 ORDER BY captured_at DESC LIMIT 30", (user_id, record["product_url"])).fetchall()]
            conn.execute(
                """INSERT INTO shopping_price_snapshot(
                    snapshot_id,user_id,product_url,platform,title,price,final_price,region,
                    membership,conditions_json,source,captured_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record["snapshot_id"], record["user_id"], record["product_url"], record["platform"],
                 record["title"], record["price"], record["final_price"], record["region"],
                 record["membership"], json.dumps(record["conditions"], ensure_ascii=False),
                 record["source"], record["captured_at"]),
            )
            if len(prior) >= 3 and record["final_price"] > 0:
                ordered = sorted(prior)
                middle = len(ordered) // 2
                baseline = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
                ratio = record["final_price"] / baseline if baseline else 1.0
                if ratio < 0.4 or ratio > 2.5:
                    confidence = _source_confidence(source)
                    conn.execute("INSERT INTO shopping_price_anomaly VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"anomaly_{uuid4().hex}", record["snapshot_id"], user_id, record["product_url"], record["final_price"], round(baseline, 2), round(ratio, 4), source, confidence, "pending", None, "", record["captured_at"], None))
        return record

    def get_monitor_poll(self, monitor_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_monitor_poll WHERE monitor_id=?", (monitor_id,)).fetchone()
        return dict(row) if row else None

    def record_monitor_poll(self, monitor_id: str, *, checked_at: str, status: str, observed_price: float, message: str) -> dict[str, Any]:
        record = {
            "monitor_id": monitor_id,
            "checked_at": checked_at,
            "status": status,
            "observed_price": round(float(observed_price), 2),
            "message": message[:500],
        }
        with self._session() as conn:
            conn.execute(
                """INSERT INTO shopping_monitor_poll(monitor_id,checked_at,status,observed_price,message)
                VALUES(?,?,?,?,?) ON CONFLICT(monitor_id) DO UPDATE SET
                checked_at=excluded.checked_at,status=excluded.status,
                observed_price=excluded.observed_price,message=excluded.message""",
                tuple(record.values()),
            )
        return record

    def price_history(self, product_url: str, user_id: str | None = None, limit: int = 365) -> dict[str, Any]:
        query = "SELECT * FROM shopping_price_snapshot WHERE product_url = ? AND NOT EXISTS (SELECT 1 FROM shopping_price_anomaly a WHERE a.snapshot_id=shopping_price_snapshot.snapshot_id AND a.status IN ('pending','dismissed'))"
        params: list[Any] = [product_url]
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY captured_at DESC LIMIT ?"
        params.append(limit)
        with self._session() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        points = [
            {"snapshot_id": row["snapshot_id"], "final_price": row["final_price"],
             "price": row["price"], "source": row["source"], "region": row["region"],
             "membership": row["membership"], "conditions": json.loads(row["conditions_json"]),
             "captured_at": row["captured_at"]}
            for row in rows
        ]
        prices = [float(item["final_price"]) for item in points]
        current = prices[0] if prices else 0.0
        sorted_prices = sorted(prices)
        percentile = (sum(1 for value in prices if value <= current) / len(prices) * 100) if prices else 0.0
        return {
            "product_url": product_url, "count": len(points), "current_price": current,
            "lowest_price": min(prices) if prices else 0.0,
            "average_price": round(sum(prices) / len(prices), 2) if prices else 0.0,
            "current_percentile": round(percentile, 1), "points": points,
            "sorted_prices": sorted_prices,
        }

    def process_latest_snapshots(self) -> dict[str, int]:
        processed = notifications = 0
        for monitor in self.list_monitors():
            if monitor["status"] not in {"watching", "target_reached"}:
                continue
            product_url = str(monitor["product"].get("url", ""))
            if not product_url:
                continue
            with self._session() as conn:
                snapshot = conn.execute(
                    "SELECT * FROM shopping_price_snapshot WHERE product_url=? ORDER BY captured_at DESC LIMIT 1",
                    (product_url,),
                ).fetchone()
                if not snapshot:
                    continue
                source = f"snapshot:{snapshot['snapshot_id']}"
                duplicate = conn.execute(
                    "SELECT 1 FROM shopping_price_check WHERE monitor_id=? AND source=?",
                    (monitor["monitor_id"], source),
                ).fetchone()
            if duplicate:
                continue
            conditions = json.loads(snapshot["conditions_json"])
            breakdown = {"page_price": snapshot["price"], **conditions, "final_price": snapshot["final_price"]}
            check = self.record_price_check(
                monitor_id=monitor["monitor_id"], breakdown=breakdown,
                stock_status="in_stock", source=source,
            )
            processed += 1
            if check["target_reached"]:
                created = self.create_notification(
                    user_id=monitor["user_id"], kind="price_reached",
                    title=f"{monitor['product'].get('title', '关注商品')} 已到目标价",
                    message=check["message"], idempotency_key=f"price:{monitor['monitor_id']}:{snapshot['snapshot_id']}",
                )
                notifications += 1 if created else 0
                if created:
                    self.record_business_event(monitor["user_id"], "monitor_target_reached", monitor["monitor_id"], idempotency_key=f"target:{monitor['monitor_id']}:{snapshot['snapshot_id']}")
        return {"processed": processed, "notifications": notifications}

    def create_notification(self, *, user_id: str, kind: str, title: str, message: str, idempotency_key: str) -> dict[str, Any] | None:
        record = {"notification_id": f"note_{uuid4().hex}", "user_id": user_id, "kind": kind,
                  "title": title, "message": message, "status": "unread",
                  "idempotency_key": idempotency_key, "created_at": utc_now_iso(), "read_at": None}
        with self._session() as conn:
            try:
                conn.execute("INSERT INTO shopping_notification VALUES(?,?,?,?,?,?,?,?,?)", tuple(record.values()))
            except Exception as exc:
                if is_integrity_error(exc):
                    return None
                raise
        record["delivery"] = deliver_notification(record, self.get_notification_preference(user_id))
        self._record_notification_delivery(record, str(record["delivery"]))
        return record

    def _record_notification_delivery(self, notification: dict[str, Any], result: str) -> dict[str, Any]:
        notification_id, user_id = str(notification["notification_id"]), str(notification["user_id"])
        with self._session() as conn:
            row = conn.execute("SELECT COALESCE(MAX(attempt),0) AS attempt FROM shopping_notification_delivery WHERE notification_id=? AND user_id=?", (notification_id, user_id)).fetchone()
            record = {"delivery_id": f"delivery_{uuid4().hex}", "notification_id": notification_id, "user_id": user_id, "attempt": int(row["attempt"]) + 1, "status": "failed" if result == "audit_only" else "delivered", "result": result, "created_at": utc_now_iso()}
            conn.execute("INSERT INTO shopping_notification_delivery(delivery_id,notification_id,user_id,attempt,status,result,created_at) VALUES(?,?,?,?,?,?,?)", tuple(record.values()))
        return record

    def list_notifications(self, user_id: str, unread_only: bool = False) -> list[dict[str, Any]]:
        if not self.get_notification_preference(user_id)["in_app_enabled"]:
            return []
        query = "SELECT * FROM shopping_notification WHERE user_id=?"
        params: list[Any] = [user_id]
        if unread_only:
            query += " AND status='unread'"
        query += " ORDER BY created_at DESC LIMIT 100"
        with self._session() as conn:
            items = [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
            for item in items:
                delivery = conn.execute("SELECT status,result,attempt,created_at FROM shopping_notification_delivery WHERE notification_id=? AND user_id=? ORDER BY attempt DESC LIMIT 1", (item["notification_id"], user_id)).fetchone()
                item["delivery"] = dict(delivery) if delivery else None
                item["target_url"] = _notification_target(str(item["kind"]))
            return items

    def mark_notification_read(self, user_id: str, notification_id: str | None = None) -> int:
        now = utc_now_iso()
        with self._session() as conn:
            if notification_id:
                cursor = conn.execute("UPDATE shopping_notification SET status='read',read_at=? WHERE notification_id=? AND user_id=?", (now, notification_id, user_id))
            else:
                cursor = conn.execute("UPDATE shopping_notification SET status='read',read_at=? WHERE user_id=? AND status='unread'", (now, user_id))
        return int(cursor.rowcount)

    def delete_notifications(self, user_id: str, notification_ids: list[str]) -> int:
        ids = [str(item) for item in notification_ids if str(item)][:100]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._session() as conn:
            owned = conn.execute(f"SELECT notification_id FROM shopping_notification WHERE user_id=? AND notification_id IN ({placeholders})", (user_id, *ids)).fetchall()
            owned_ids = [row["notification_id"] for row in owned]
            if not owned_ids:
                return 0
            owned_placeholders = ",".join("?" for _ in owned_ids)
            conn.execute(f"DELETE FROM shopping_notification_delivery WHERE user_id=? AND notification_id IN ({owned_placeholders})", (user_id, *owned_ids))
            return int(conn.execute(f"DELETE FROM shopping_notification WHERE user_id=? AND notification_id IN ({owned_placeholders})", (user_id, *owned_ids)).rowcount)

    def retry_notification(self, user_id: str, notification_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_notification WHERE user_id=? AND notification_id=?", (user_id, notification_id)).fetchone()
        if not row:
            return None
        notification = dict(row)
        result = deliver_notification(notification, self.get_notification_preference(user_id))
        return self._record_notification_delivery(notification, result)

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
        self.upsert_product_record(user_id, product)
        self.record_business_event(user_id, "monitor_created", monitor_id, idempotency_key=f"monitor:{monitor_id}")
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
        items = [_row_to_monitor(row) for row in rows]
        with self._session() as conn:
            for item in items:
                preference = conn.execute("SELECT group_name,frequency FROM shopping_monitor_preference WHERE monitor_id=? AND user_id=?", (item["monitor_id"], item["user_id"])).fetchone()
                item["group_name"] = preference["group_name"] if preference else "默认分组"
                item["frequency"] = preference["frequency"] if preference else "daily"
        return items

    def save_monitor_preference(self, user_id: str, monitor_id: str, group_name: str, frequency: str) -> dict[str, Any]:
        if frequency not in {"realtime", "daily", "weekly"}:
            raise ValueError("invalid monitor frequency")
        group_name = group_name.strip()[:40] or "默认分组"
        now = utc_now_iso()
        with self._session() as conn:
            if not conn.execute("SELECT 1 FROM shopping_price_monitor WHERE monitor_id=? AND user_id=?", (monitor_id, user_id)).fetchone():
                raise ValueError("monitor not found")
            conn.execute("INSERT INTO shopping_monitor_preference(monitor_id,user_id,group_name,frequency,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(monitor_id) DO UPDATE SET group_name=excluded.group_name,frequency=excluded.frequency,updated_at=excluded.updated_at", (monitor_id, user_id, group_name, frequency, now))
        return {"monitor_id": monitor_id, "group_name": group_name, "frequency": frequency, "updated_at": now}

    def save_budget_pool(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now, pool_id = utc_now_iso(), str(payload.get("pool_id") or f"pool_{uuid4().hex}")
        name = str(payload.get("name") or "").strip()[:60]
        target = max(0, float(payload.get("target_amount") or 0))
        spent = max(0, float(payload.get("spent_amount") or 0))
        if not name or target <= 0:
            raise ValueError("budget pool name and positive target are required")
        with self._session() as conn:
            old = conn.execute("SELECT user_id,created_at FROM shopping_budget_pool WHERE pool_id=?", (pool_id,)).fetchone()
            if old and old["user_id"] != user_id:
                raise ValueError("budget pool does not belong to user")
            created = old["created_at"] if old else now
            conn.execute("INSERT INTO shopping_budget_pool(pool_id,user_id,name,target_amount,spent_amount,currency,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(pool_id) DO UPDATE SET name=excluded.name,target_amount=excluded.target_amount,spent_amount=excluded.spent_amount,currency=excluded.currency,status=excluded.status,updated_at=excluded.updated_at", (pool_id, user_id, name, target, spent, str(payload.get("currency") or "CNY")[:3].upper(), str(payload.get("status") or "active"), created, now))
            row = conn.execute("SELECT * FROM shopping_budget_pool WHERE pool_id=?", (pool_id,)).fetchone()
        return dict(row)

    def list_budget_pools(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM shopping_budget_pool WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()]

    def record_savings(self, user_id: str, source_type: str, source_id: str, amount: float, title: str, occurred_at: str | None = None) -> dict[str, Any] | None:
        if source_type not in {"purchase", "price_protection", "coupon"} or amount <= 0 or not source_id:
            raise ValueError("invalid savings entry")
        record = {"entry_id": f"saving_{uuid4().hex}", "user_id": user_id, "source_type": source_type, "source_id": source_id, "amount": round(float(amount), 2), "title": title.strip()[:120], "occurred_at": occurred_at or utc_now_iso(), "created_at": utc_now_iso()}
        with self._session() as conn:
            try:
                conn.execute("INSERT INTO shopping_savings_ledger(entry_id,user_id,source_type,source_id,amount,title,occurred_at,created_at) VALUES(?,?,?,?,?,?,?,?)", tuple(record.values()))
            except Exception as exc:
                if is_integrity_error(exc):
                    return None
                raise
        return record

    def list_savings(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM shopping_savings_ledger WHERE user_id=? ORDER BY occurred_at DESC LIMIT 500", (user_id,)).fetchall()]
        return {"items": rows, "total": round(sum(float(item["amount"]) for item in rows), 2)}

    def price_calendar(self, user_id: str, days: int = 90) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        with self._session() as conn:
            rows = conn.execute("SELECT substr(captured_at,1,10) AS day,COUNT(*) AS observations,MIN(final_price) AS lowest_price,AVG(final_price) AS average_price FROM shopping_price_snapshot WHERE user_id=? AND captured_at>=? AND NOT EXISTS (SELECT 1 FROM shopping_price_anomaly a WHERE a.snapshot_id=shopping_price_snapshot.snapshot_id AND a.status IN ('pending','dismissed')) GROUP BY substr(captured_at,1,10) ORDER BY day", (user_id, cutoff)).fetchall()
        return [dict(row) for row in rows]

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

    def update_monitor_status(self, monitor_id: str, status: str, *, actor_id: str, reason: str = "", action: str | None = None) -> dict[str, Any] | None:
        allowed = {
            "watching": {"paused", "expired", "target_reached"},
            "target_reached": {"watching", "paused", "expired"},
            "paused": {"watching", "expired"},
            "expired": {"watching"},
        }
        monitor = self.get_monitor(monitor_id)
        if not monitor:
            return None
        if status not in allowed.get(monitor["status"], set()):
            raise ValueError(f"invalid monitor transition: {monitor['status']} -> {status}")
        now = utc_now_iso()
        with self._session() as conn:
            conn.execute(
                "UPDATE shopping_price_monitor SET status=?, updated_at=?, last_message=? WHERE monitor_id=?",
                (status, now, reason or f"状态已更新为 {status}", monitor_id),
            )
            conn.execute(
                "INSERT INTO shopping_monitor_action(action_id,monitor_id,actor_id,action,from_status,to_status,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"mact_{uuid4().hex}", monitor_id, actor_id, action or status, monitor["status"], status, reason, now),
            )
        return self.get_monitor(monitor_id)

    def delete_monitor(self, monitor_id: str, *, actor_id: str, reason: str = "") -> bool:
        monitor = self.get_monitor(monitor_id)
        if not monitor:
            return False
        now = utc_now_iso()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO shopping_monitor_action(action_id,monitor_id,actor_id,action,from_status,to_status,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"mact_{uuid4().hex}", monitor_id, actor_id, "delete", monitor["status"], None, reason, now),
            )
            conn.execute("DELETE FROM shopping_monitor_preference WHERE monitor_id=?", (monitor_id,))
            conn.execute("DELETE FROM shopping_price_monitor WHERE monitor_id=?", (monitor_id,))
        return True

    def list_monitor_actions(self, monitor_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM shopping_monitor_action"
        params: list[Any] = []
        if monitor_id:
            query += " WHERE monitor_id=?"
            params.append(monitor_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._session() as conn:
            return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]

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

    def create_purchase(
        self,
        *,
        user_id: str,
        product: dict[str, Any],
        paid_price: float,
        platform: str,
        store_name: str,
        purchased_at: str | None,
        price_protection_days: int,
        return_days: int,
        warranty_months: int,
        consumable_cycle_days: int | None,
        notes: str,
    ) -> dict[str, Any]:
        purchase_id = f"buy_{uuid4().hex}"
        purchased_dt = _parse_or_now(purchased_at)
        price_protection_deadline = _deadline(purchased_dt, days=price_protection_days) if price_protection_days else None
        return_deadline = _deadline(purchased_dt, days=return_days) if return_days else None
        warranty_deadline = _deadline(purchased_dt, days=warranty_months * 30) if warranty_months else None
        consumable_reminder_at = _deadline(purchased_dt, days=consumable_cycle_days) if consumable_cycle_days else None
        reminders = _build_purchase_reminders(
            price_protection_deadline=price_protection_deadline,
            return_deadline=return_deadline,
            warranty_deadline=warranty_deadline,
            consumable_reminder_at=consumable_reminder_at,
        )
        now = utc_now_iso()
        record = {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "product": product,
            "paid_price": round(float(paid_price), 2),
            "platform": platform or product.get("platform") or "",
            "store_name": store_name,
            "purchased_at": purchased_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "price_protection_deadline": price_protection_deadline,
            "return_deadline": return_deadline,
            "warranty_deadline": warranty_deadline,
            "consumable_reminder_at": consumable_reminder_at,
            "status": "active",
            "reminders": reminders,
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        }
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO shopping_purchase_record(
                    purchase_id, user_id, product_json, paid_price, platform, store_name,
                    purchased_at, price_protection_deadline, return_deadline, warranty_deadline,
                    consumable_reminder_at, status, reminders_json, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_id,
                    user_id,
                    json.dumps(product, ensure_ascii=False),
                    record["paid_price"],
                    record["platform"],
                    store_name,
                    record["purchased_at"],
                    price_protection_deadline,
                    return_deadline,
                    warranty_deadline,
                    consumable_reminder_at,
                    record["status"],
                    json.dumps(reminders, ensure_ascii=False),
                    notes,
                    now,
                    now,
                ),
            )
        self.upsert_product_record(user_id, product)
        reference_price = float(product.get("price") or paid_price)
        self.record_business_event(user_id, "purchase_confirmed", purchase_id, max(0.0, reference_price - float(paid_price)), idempotency_key=f"purchase:{purchase_id}")
        saved = max(0.0, reference_price - float(paid_price))
        if saved:
            self.record_savings(user_id, "purchase", purchase_id, saved, f"购买节省 · {product.get('title') or '商品'}", record["purchased_at"])
        return record

    def list_purchases(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT purchase_id, user_id, product_json, paid_price, platform, store_name,
                   purchased_at, price_protection_deadline, return_deadline, warranty_deadline,
                   consumable_reminder_at, status, reminders_json, notes, created_at, updated_at
            FROM shopping_purchase_record
        """
        params: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY purchased_at DESC"
        with self._session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_purchase(row) for row in rows]

    def update_purchase(self, user_id: str, purchase_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        allowed_status = {"active", "received", "price_protection", "returning", "returned", "warranty", "completed"}
        status = str(payload.get("status") or "")
        if status and status not in allowed_status:
            raise ValueError("invalid purchase status")
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_purchase_record WHERE purchase_id=? AND user_id=?", (purchase_id, user_id)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE shopping_purchase_record SET status=?,notes=?,updated_at=? WHERE purchase_id=? AND user_id=?", (status or row["status"], str(payload.get("notes")) if payload.get("notes") is not None else row["notes"], utc_now_iso(), purchase_id, user_id))
            updated = conn.execute("SELECT * FROM shopping_purchase_record WHERE purchase_id=? AND user_id=?", (purchase_id, user_id)).fetchone()
        return _row_to_purchase(updated)

    def create_purchase_attachment(self, user_id: str, purchase_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        with self._session() as conn:
            if not conn.execute("SELECT 1 FROM shopping_purchase_record WHERE purchase_id=? AND user_id=?", (purchase_id, user_id)).fetchone():
                raise ValueError("purchase not found")
            record = {"attachment_id": f"att_{uuid4().hex}", "purchase_id": purchase_id, "user_id": user_id, **metadata, "created_at": utc_now_iso()}
            conn.execute("INSERT INTO shopping_purchase_attachment VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(record[key] for key in ("attachment_id", "purchase_id", "user_id", "attachment_type", "original_name", "content_type", "size_bytes", "sha256", "storage_backend", "storage_key", "created_at")))
        return record

    def list_purchase_attachments(self, user_id: str, purchase_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT attachment_id,purchase_id,attachment_type,original_name,content_type,size_bytes,sha256,created_at FROM shopping_purchase_attachment WHERE user_id=? AND purchase_id=? ORDER BY created_at DESC", (user_id, purchase_id)).fetchall()
        return [dict(row) for row in rows]

    def get_purchase_attachment(self, user_id: str, attachment_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_purchase_attachment WHERE attachment_id=? AND user_id=?", (attachment_id, user_id)).fetchone()
        return dict(row) if row else None

    def save_price_protection_claim(self, user_id: str, purchase_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status") or "submitted")
        if status not in {"submitted", "succeeded", "rejected", "cancelled"}:
            raise ValueError("invalid price protection status")
        requested = max(0.0, round(float(payload.get("requested_amount") or 0), 2))
        approved = max(0.0, round(float(payload.get("approved_amount") or 0), 2))
        if status == "succeeded" and approved <= 0:
            raise ValueError("approved amount is required for a successful claim")
        now = utc_now_iso()
        with self._session() as conn:
            purchase = conn.execute("SELECT product_json FROM shopping_purchase_record WHERE purchase_id=? AND user_id=?", (purchase_id, user_id)).fetchone()
            if not purchase:
                raise ValueError("purchase not found")
            claim_id = str(payload.get("claim_id") or f"claim_{uuid4().hex}")
            old = conn.execute("SELECT * FROM shopping_price_protection_claim WHERE claim_id=?", (claim_id,)).fetchone()
            if old and (old["user_id"] != user_id or old["purchase_id"] != purchase_id):
                raise ValueError("claim does not belong to purchase")
            created_at = old["created_at"] if old else now
            submitted_at = old["submitted_at"] if old else now
            resolved_at = now if status in {"succeeded", "rejected", "cancelled"} else None
            conn.execute("""INSERT INTO shopping_price_protection_claim(
                claim_id,purchase_id,user_id,status,requested_amount,approved_amount,evidence_source,notes,
                submitted_at,resolved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(claim_id) DO UPDATE SET status=excluded.status,requested_amount=excluded.requested_amount,
                approved_amount=excluded.approved_amount,evidence_source=excluded.evidence_source,notes=excluded.notes,
                resolved_at=excluded.resolved_at,updated_at=excluded.updated_at""",
                (claim_id, purchase_id, user_id, status, requested, approved, "user_reported", str(payload.get("notes") or "")[:1000], submitted_at, resolved_at, created_at, now))
            row = conn.execute("SELECT * FROM shopping_price_protection_claim WHERE claim_id=?", (claim_id,)).fetchone()
            product = json.loads(purchase["product_json"])
        if status == "succeeded":
            self.record_savings(user_id, "price_protection", claim_id, approved, f"保价节省 · {product.get('title') or '商品'}", resolved_at)
        return dict(row)

    def list_price_protection_claims(self, user_id: str, purchase_id: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM shopping_price_protection_claim WHERE user_id=?", [user_id]
        if purchase_id:
            query += " AND purchase_id=?"
            params.append(purchase_id)
        query += " ORDER BY updated_at DESC"
        with self._session() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def create_support_ticket(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        subject, content = str(payload.get("subject") or "").strip(), str(payload.get("content") or "").strip()
        if not subject or not content:
            raise ValueError("subject and content are required")
        purchase_id = str(payload.get("purchase_id") or "") or None
        now, ticket_id = utc_now_iso(), f"ticket_{uuid4().hex}"
        with self._session() as conn:
            if purchase_id and not conn.execute("SELECT 1 FROM shopping_purchase_record WHERE purchase_id=? AND user_id=?", (purchase_id, user_id)).fetchone():
                raise ValueError("purchase not found")
            conn.execute("INSERT INTO shopping_support_ticket VALUES(?,?,?,?,?,?,?,?,?)", (ticket_id, user_id, purchase_id, str(payload.get("category") or "general")[:40], subject[:160], "open", "normal", now, now))
            conn.execute("INSERT INTO shopping_support_message VALUES(?,?,?,?,?,?)", (f"msg_{uuid4().hex}", ticket_id, user_id, "user", content[:5000], now))
            sla_due = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            conn.execute("INSERT INTO shopping_support_case VALUES(?,?,?,?,?,?,?,?)", (ticket_id, None, sla_due, None, None, None, "", now))
        return self.get_support_ticket(user_id, ticket_id) or {}

    def get_support_ticket(self, user_id: str, ticket_id: str, admin: bool = False) -> dict[str, Any] | None:
        with self._session() as conn:
            query, params = "SELECT * FROM shopping_support_ticket WHERE ticket_id=?", [ticket_id]
            if not admin:
                query += " AND user_id=?"; params.append(user_id)
            row = conn.execute(query, tuple(params)).fetchone()
            if not row:
                return None
            messages = conn.execute("SELECT * FROM shopping_support_message WHERE ticket_id=? ORDER BY created_at", (ticket_id,)).fetchall()
            case = conn.execute("SELECT * FROM shopping_support_case WHERE ticket_id=?", (ticket_id,)).fetchone()
        return {**dict(row), **(dict(case) if case else {}), "messages": [dict(message) for message in messages]}

    def list_support_tickets(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM shopping_support_ticket", []
        if user_id:
            query += " WHERE user_id=?"; params.append(user_id)
        query += " ORDER BY updated_at DESC LIMIT 500"
        with self._session() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            items = []
            for row in rows:
                case = conn.execute("SELECT * FROM shopping_support_case WHERE ticket_id=?", (row["ticket_id"],)).fetchone()
                items.append({**dict(row), **(dict(case) if case else {})})
        return items

    def reply_support_ticket(self, actor_id: str, ticket_id: str, content: str, *, admin: bool = False, status: str | None = None) -> dict[str, Any]:
        if status and status not in {"open", "in_progress", "waiting_user", "resolved", "closed"}:
            raise ValueError("invalid ticket status")
        if not content.strip():
            raise ValueError("message is required")
        ticket = self.get_support_ticket(actor_id, ticket_id, admin=admin)
        if not ticket:
            raise ValueError("ticket not found")
        next_status = status or ("waiting_user" if admin else "open")
        now = utc_now_iso()
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_support_message VALUES(?,?,?,?,?,?)", (f"msg_{uuid4().hex}", ticket_id, actor_id, "admin" if admin else "user", content.strip()[:5000], now))
            conn.execute("UPDATE shopping_support_ticket SET status=?,updated_at=? WHERE ticket_id=?", (next_status, now, ticket_id))
            if admin:
                conn.execute("UPDATE shopping_support_case SET first_response_at=COALESCE(first_response_at,?),updated_at=? WHERE ticket_id=?", (now, now, ticket_id))
        return self.get_support_ticket(actor_id, ticket_id, admin=admin) or {}

    def update_support_case(self, actor_id: str, ticket_id: str, payload: dict[str, Any], *, admin: bool = False) -> dict[str, Any]:
        ticket = self.get_support_ticket(actor_id, ticket_id, admin=admin)
        if not ticket:
            raise ValueError("ticket not found")
        status = str(payload.get("status") or ticket["status"])
        allowed = {"open", "closed"} if not admin else {"open", "in_progress", "waiting_user", "resolved", "closed"}
        if status not in allowed:
            raise ValueError("invalid ticket status")
        satisfaction = payload.get("satisfaction")
        if satisfaction is not None and (admin or int(satisfaction) not in range(1, 6)):
            raise ValueError("satisfaction must be between 1 and 5")
        now = utc_now_iso()
        with self._session() as conn:
            if admin and payload.get("assigned_to") is not None:
                conn.execute("UPDATE shopping_support_case SET assigned_to=?,updated_at=? WHERE ticket_id=?", (str(payload.get("assigned_to") or "")[:80] or None, now, ticket_id))
            if satisfaction is not None:
                conn.execute("UPDATE shopping_support_case SET satisfaction=?,satisfaction_note=?,updated_at=? WHERE ticket_id=?", (int(satisfaction), str(payload.get("satisfaction_note") or "")[:500], now, ticket_id))
            conn.execute("UPDATE shopping_support_ticket SET status=?,updated_at=? WHERE ticket_id=?", (status, now, ticket_id))
            conn.execute("UPDATE shopping_support_case SET closed_at=?,updated_at=? WHERE ticket_id=?", (now if status == "closed" else None, now, ticket_id))
        return self.get_support_ticket(actor_id, ticket_id, admin=admin) or {}

    def save_campaign(self, payload: dict[str, Any], campaign_id: str | None = None) -> dict[str, Any]:
        now, campaign_id = utc_now_iso(), campaign_id or f"campaign_{uuid4().hex}"
        name, title = str(payload.get("name") or "").strip()[:120], str(payload.get("title") or "").strip()[:160]
        if not name or not title:
            raise ValueError("campaign name and title are required")
        status = str(payload.get("status") or "draft")
        if status not in {"draft", "scheduled", "published", "paused", "ended"}:
            raise ValueError("invalid campaign status")
        placement = str(payload.get("placement") or "discover")
        if placement not in {"discover", "category", "savings"}:
            raise ValueError("invalid campaign placement")
        target_url = str(payload.get("target_url") or "").strip()[:1000]
        if target_url and not target_url.startswith(("/", "https://", "http://")):
            raise ValueError("campaign target must be an internal path or http/https URL")
        with self._session() as conn:
            old = conn.execute("SELECT created_at FROM shopping_campaign WHERE campaign_id=?", (campaign_id,)).fetchone()
            created_at = old["created_at"] if old else now
            conn.execute("""INSERT INTO shopping_campaign VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET name=excluded.name,title=excluded.title,summary=excluded.summary,placement=excluded.placement,target_url=excluded.target_url,status=excluded.status,starts_at=excluded.starts_at,ends_at=excluded.ends_at,updated_at=excluded.updated_at""", (campaign_id, name, title, str(payload.get("summary") or "").strip()[:500], placement, target_url or None, status, payload.get("starts_at"), payload.get("ends_at"), created_at, now))
            row = conn.execute("SELECT * FROM shopping_campaign WHERE campaign_id=?", (campaign_id,)).fetchone()
        return dict(row)

    def list_campaigns(self, public_only: bool = False) -> list[dict[str, Any]]:
        now = utc_now_iso()
        query, params = "SELECT * FROM shopping_campaign", []
        if public_only:
            query += " WHERE status='published' AND (starts_at IS NULL OR starts_at<=?) AND (ends_at IS NULL OR ends_at>?)"; params.extend([now, now])
        query += " ORDER BY updated_at DESC LIMIT 200"
        with self._session() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def delete_campaign(self, campaign_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("DELETE FROM shopping_campaign WHERE campaign_id=?", (campaign_id,)).rowcount > 0

    def save_risk_rule(self, payload: dict[str, Any], rule_id: str | None = None) -> dict[str, Any]:
        field_name, severity, action = str(payload.get("field_name") or "title"), str(payload.get("severity") or "medium"), str(payload.get("action") or "warn")
        if field_name not in {"title", "platform", "condition", "notes", "model"} or severity not in {"low", "medium", "high"} or action not in {"warn", "block"}:
            raise ValueError("invalid risk rule")
        pattern = str(payload.get("pattern") or "").strip().lower()[:120]
        if not pattern:
            raise ValueError("risk pattern is required")
        now, rule_id = utc_now_iso(), rule_id or f"rule_{uuid4().hex}"
        code = str(payload.get("code") or rule_id)[:80]
        with self._session() as conn:
            old = conn.execute("SELECT created_at FROM shopping_risk_rule WHERE rule_id=?", (rule_id,)).fetchone()
            conflict = conn.execute("SELECT rule_id FROM shopping_risk_rule WHERE code=? AND rule_id<>?", (code, rule_id)).fetchone()
            if conflict:
                raise ValueError("risk rule code already exists")
            created_at = old["created_at"] if old else now
            conn.execute("""INSERT INTO shopping_risk_rule VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO UPDATE SET code=excluded.code,name=excluded.name,field_name=excluded.field_name,pattern=excluded.pattern,severity=excluded.severity,action=excluded.action,enabled=excluded.enabled,updated_at=excluded.updated_at""", (rule_id, code, str(payload.get("name") or "风控规则")[:120], field_name, pattern, severity, action, 1 if payload.get("enabled", True) else 0, created_at, now))
            row = conn.execute("SELECT * FROM shopping_risk_rule WHERE rule_id=?", (rule_id,)).fetchone()
        self.reload_risk_rule_snapshot()
        return dict(row)

    def list_risk_rules(self) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_risk_rule ORDER BY updated_at DESC LIMIT 500").fetchall()
        return [dict(row) for row in rows]

    def delete_risk_rule(self, rule_id: str) -> bool:
        with self._session() as conn:
            deleted = conn.execute("DELETE FROM shopping_risk_rule WHERE rule_id=?", (rule_id,)).rowcount > 0
        if deleted:
            self.reload_risk_rule_snapshot()
        return deleted

    def reload_risk_rule_snapshot(self) -> dict[str, Any]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_risk_rule WHERE enabled=1 ORDER BY updated_at DESC LIMIT 500").fetchall()
        snapshot = tuple(_risk_rule_snapshot_row(dict(row)) for row in rows)
        with self._risk_rules_lock:
            standby = 1 - self._active_risk_rule_buffer
            self._risk_rule_buffers[standby] = snapshot
            self._active_risk_rule_buffer = standby
            active = self._active_risk_rule_buffer
        return {"active_buffer": active, "rule_count": len(snapshot), "reloaded_at": utc_now_iso()}

    def risk_rule_snapshot_status(self) -> dict[str, Any]:
        snapshot = self._risk_rules_snapshot()
        return {
            "active_buffer": self._active_risk_rule_buffer,
            "standby_buffer": 1 - self._active_risk_rule_buffer,
            "rule_count": len(snapshot),
            "strategy": "double_buffer_atomic_snapshot",
        }

    def _risk_rules_snapshot(self) -> tuple[dict[str, Any], ...]:
        return self._risk_rule_buffers[self._active_risk_rule_buffer]

    def evaluate_risk_rules(self, product: dict[str, Any]) -> list[dict[str, Any]]:
        matches = []
        for rule in self._risk_rules_snapshot():
            value = str(product.get(str(rule["field_name"])) or "").lower()
            if str(rule["pattern"]) in value:
                matches.append({"rule_id": rule["rule_id"], "code": rule["code"], "name": rule["name"], "severity": rule["severity"], "action": rule["action"]})
        return matches

    def record_admin_audit(self, actor_id: str, action: str, target_type: str, target_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {"audit_id": f"audit_{uuid4().hex}", "actor_id": actor_id, "action": action, "target_type": target_type, "target_id": target_id, "metadata": metadata or {}, "created_at": utc_now_iso()}
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_admin_audit VALUES(?,?,?,?,?,?,?)", (record["audit_id"], actor_id, action, target_type, target_id, json.dumps(record["metadata"], ensure_ascii=False), record["created_at"]))
        return record

    def list_admin_audits(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_admin_audit ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [_decode_json_columns(row, {"metadata_json": "metadata"}) for row in rows]

    def list_all_shares(self) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT share_id,user_id,share_type,title,status,created_at,expires_at,revoked_at FROM shopping_share ORDER BY created_at DESC LIMIT 500").fetchall()
        return [dict(row) for row in rows]

    def admin_revoke_share(self, share_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("UPDATE shopping_share SET status='revoked',revoked_at=? WHERE share_id=? AND status='active'", (utc_now_iso(), share_id)).rowcount > 0

    def save_experiment(self, payload: dict[str, Any], experiment_id: str | None = None) -> dict[str, Any]:
        code, name = str(payload.get("code") or "").strip()[:80], str(payload.get("name") or "").strip()[:120]
        variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        variants = [str(item).strip()[:40] for item in variants if str(item).strip()][:5]
        status = str(payload.get("status") or "draft")
        if not code or not name or len(variants) < 2 or status not in {"draft", "running", "paused", "completed"}:
            raise ValueError("experiment requires code, name, 2-5 variants, and a valid status")
        now, experiment_id = utc_now_iso(), experiment_id or f"experiment_{uuid4().hex}"
        with self._session() as conn:
            old = conn.execute("SELECT created_at FROM shopping_experiment WHERE experiment_id=?", (experiment_id,)).fetchone()
            conflict = conn.execute("SELECT experiment_id FROM shopping_experiment WHERE code=? AND experiment_id<>?", (code, experiment_id)).fetchone()
            if conflict:
                raise ValueError("experiment code already exists")
            created_at = old["created_at"] if old else now
            conn.execute("""INSERT INTO shopping_experiment VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET code=excluded.code,name=excluded.name,variants_json=excluded.variants_json,status=excluded.status,starts_at=excluded.starts_at,ends_at=excluded.ends_at,updated_at=excluded.updated_at""", (experiment_id, code, name, json.dumps(variants, ensure_ascii=False), status, payload.get("starts_at"), payload.get("ends_at"), created_at, now))
            row = conn.execute("SELECT * FROM shopping_experiment WHERE experiment_id=?", (experiment_id,)).fetchone()
        return _decode_json_columns(row, {"variants_json": "variants"})

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_experiment ORDER BY updated_at DESC LIMIT 200").fetchall()
        return [_decode_json_columns(row, {"variants_json": "variants"}) for row in rows]

    def assign_experiment(self, user_id: str, code: str) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_experiment WHERE code=? AND status='running' AND (starts_at IS NULL OR starts_at<=?) AND (ends_at IS NULL OR ends_at>?)", (code, now, now)).fetchone()
            if not row:
                return None
            existing = conn.execute("SELECT variant,created_at FROM shopping_experiment_assignment WHERE experiment_id=? AND user_id=?", (row["experiment_id"], user_id)).fetchone()
            variants = json.loads(row["variants_json"])
            if existing:
                variant, created_at = existing["variant"], existing["created_at"]
            else:
                index = int(hashlib.sha256(f"{row['experiment_id']}:{user_id}".encode()).hexdigest()[:8], 16) % len(variants)
                variant, created_at = variants[index], now
                conn.execute("INSERT INTO shopping_experiment_assignment VALUES(?,?,?,?)", (row["experiment_id"], user_id, variant, created_at))
        return {"experiment_id": row["experiment_id"], "code": code, "variant": variant, "created_at": created_at}

    def save_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with self._session() as conn:
            existing = conn.execute("SELECT created_at FROM shopping_user_profile WHERE user_id=?", (user_id,)).fetchone()
            created = existing["created_at"] if existing else now
            conn.execute("""INSERT INTO shopping_user_profile(user_id,profile_json,created_at,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json,updated_at=excluded.updated_at""",
                (user_id, json.dumps(profile, ensure_ascii=False), created, now))
        return {"user_id": user_id, "profile": profile, "created_at": created, "updated_at": now}

    def get_profile(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_user_profile WHERE user_id=?", (user_id,)).fetchone()
        return {"user_id": user_id, "profile": json.loads(row["profile_json"]), "created_at": row["created_at"], "updated_at": row["updated_at"]} if row else {"user_id": user_id, "profile": {}}

    def get_llm_config(self, user_id: str, *, include_secret: bool = False) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_llm_user_config WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"configured": False, "enabled": False, "model": "", "vision_model": "", "wire_api": "responses", "base_url": ""}
        try:
            api_key = decrypt_user_secret(str(row["api_key_encrypted"]))
        except Exception:
            api_key = ""
        result = {
            "configured": bool(api_key), "enabled": bool(row["enabled"]) and bool(api_key),
            "api_key_hint": f"...{api_key[-4:]}" if len(api_key) >= 4 else None,
            "base_url": row["base_url"], "model": row["model"], "vision_model": row["vision_model"],
            "wire_api": row["wire_api"], "last_test_status": row["last_test_status"],
            "last_test_at": row["last_test_at"], "last_test_error": row["last_test_error"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        if include_secret:
            result["api_key"] = api_key
        return result

    def save_llm_config(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_llm_config(user_id, include_secret=True)
        api_key = str(payload.get("api_key") or current.get("api_key") or "").strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        if not api_key or "\n" in api_key or "\r" in api_key or len(api_key) > 512:
            raise ValueError("请输入有效的 LLM API Key")
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if base_url:
            _validate_llm_base_url(base_url)
        model = _validate_llm_model(str(payload.get("model") or current.get("model") or "gpt-5.5").strip())
        vision_model = _validate_llm_model(str(payload.get("vision_model") or current.get("vision_model") or model).strip())
        wire_api = str(payload.get("wire_api") or current.get("wire_api") or "responses").strip().lower()
        if wire_api not in {"responses", "chat_completions"}:
            raise ValueError("协议只能是 responses 或 chat_completions")
        now = utc_now_iso()
        with self._session() as conn:
            existing = conn.execute("SELECT created_at FROM shopping_llm_user_config WHERE user_id=?", (user_id,)).fetchone()
            created = existing["created_at"] if existing else now
            conn.execute("""INSERT INTO shopping_llm_user_config(user_id,api_key_encrypted,base_url,model,vision_model,wire_api,enabled,last_test_status,last_test_at,last_test_error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,?,?) ON CONFLICT(user_id) DO UPDATE SET api_key_encrypted=excluded.api_key_encrypted,base_url=excluded.base_url,model=excluded.model,vision_model=excluded.vision_model,wire_api=excluded.wire_api,enabled=excluded.enabled,updated_at=excluded.updated_at""",
                (user_id, encrypt_user_secret(api_key), base_url, model, vision_model, wire_api, 1 if payload.get("enabled", True) else 0, created, now))
            conn.execute("UPDATE shopping_llm_user_config SET last_test_status=NULL,last_test_at=NULL,last_test_error=NULL WHERE user_id=?", (user_id,))
        return self.get_llm_config(user_id)

    def delete_llm_config(self, user_id: str) -> bool:
        with self._session() as conn:
            cursor = conn.execute("DELETE FROM shopping_llm_user_config WHERE user_id=?", (user_id,))
        return bool(cursor.rowcount)

    def save_llm_test_result(self, user_id: str, status: str, error: str | None = None) -> dict[str, Any]:
        now = utc_now_iso()
        with self._session() as conn:
            conn.execute("UPDATE shopping_llm_user_config SET last_test_status=?,last_test_at=?,last_test_error=?,updated_at=? WHERE user_id=?", (status, now, (error or "")[:500] or None, now, user_id))
        return self.get_llm_config(user_id)

    def save_item(self, user_id: str, item_type: str, reference_key: str, label: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
        if item_type not in {"favorite", "recent", "brand"}:
            raise ValueError("invalid saved item type")
        reference_key = reference_key.strip()
        if not reference_key:
            raise ValueError("reference_key is required")
        now, saved_id = utc_now_iso(), f"saved_{uuid4().hex}"
        with self._session() as conn:
            existing = conn.execute("SELECT saved_id,created_at FROM shopping_saved_item WHERE user_id=? AND item_type=? AND reference_key=?", (user_id, item_type, reference_key)).fetchone()
            created = existing["created_at"] if existing else now
            saved_id = existing["saved_id"] if existing else saved_id
            conn.execute("""INSERT INTO shopping_saved_item(saved_id,user_id,item_type,reference_key,label,product_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id,item_type,reference_key) DO UPDATE SET label=excluded.label,product_json=excluded.product_json,updated_at=excluded.updated_at""", (saved_id, user_id, item_type, reference_key, label.strip() or reference_key, json.dumps(product or {}, ensure_ascii=False), created, now))
        product_ref = self.upsert_product_record(user_id, product or {}) if item_type != "brand" and product else None
        return {"saved_id": saved_id, "user_id": user_id, "item_type": item_type, "reference_key": reference_key, "label": label.strip() or reference_key, "product": product or {}, "product_ref": product_ref, "created_at": created, "updated_at": now}

    @staticmethod
    def product_ref(product: dict[str, Any]) -> str:
        url = str(product.get("url") or "").strip().lower()
        identity = url or "|".join(str(product.get(key) or "").strip().lower() for key in ("brand", "model", "sku"))
        identity = identity.strip("|") or "|".join(str(product.get(key) or "").strip().lower() for key in ("title", "platform"))
        if not identity.strip("|"):
            raise ValueError("product URL, title, or identity is required")
        return f"prd_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _product_keys(product: dict[str, Any]) -> tuple[str, str]:
        brand = str(product.get("brand") or "").strip().lower()
        model = str(product.get("model") or "").strip().lower()
        sku = str(product.get("sku") or "").strip().lower()
        family = "|".join((brand, model)).strip("|")
        canonical = "|".join((family, sku)).strip("|") or str(product.get("url") or "").strip().lower()
        canonical = canonical or "|".join(str(product.get(key) or "").strip().lower() for key in ("title", "platform")).strip("|")
        return canonical, family or canonical

    def upsert_product_record(self, user_id: str, product: dict[str, Any]) -> str:
        product_ref = self.product_ref(product)
        canonical, family = self._product_keys(product)
        now = utc_now_iso()
        with self._session() as conn:
            old = conn.execute("SELECT created_at,product_json FROM shopping_product_record WHERE product_ref=? AND user_id=?", (product_ref, user_id)).fetchone()
            serialized = json.dumps(product, ensure_ascii=False, sort_keys=True)
            old_serialized = json.dumps(json.loads(old["product_json"]), ensure_ascii=False, sort_keys=True) if old else None
            if serialized != old_serialized:
                row = conn.execute("SELECT COALESCE(MAX(version),0) AS version FROM shopping_product_version WHERE product_ref=? AND user_id=?", (product_ref, user_id)).fetchone()
                version = int(row["version"] or 0) + 1
                source = str(product.get("source") or product.get("_source") or "user_input")[:80]
                conn.execute("INSERT INTO shopping_product_version VALUES(?,?,?,?,?,?,?,?)", (f"pver_{uuid4().hex}", product_ref, user_id, version, serialized, source, _source_confidence(source), now))
            conn.execute("""INSERT INTO shopping_product_record(product_ref,user_id,canonical_key,family_key,product_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_ref,user_id) DO UPDATE SET canonical_key=excluded.canonical_key,
                family_key=excluded.family_key,product_json=excluded.product_json,updated_at=excluded.updated_at""",
                (product_ref, user_id, canonical, family, json.dumps(product, ensure_ascii=False), old["created_at"] if old else now, now))
        return product_ref

    def list_price_anomalies(self, status: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM shopping_price_anomaly", []
        if status:
            query += " WHERE status=?"; params.append(status)
        query += " ORDER BY created_at DESC LIMIT 500"
        with self._session() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def review_price_anomaly(self, anomaly_id: str, actor_id: str, status: str, note: str = "") -> dict[str, Any] | None:
        if status not in {"accepted", "dismissed"}:
            raise ValueError("invalid anomaly review status")
        with self._session() as conn:
            conn.execute("UPDATE shopping_price_anomaly SET status=?,reviewed_by=?,review_note=?,reviewed_at=? WHERE anomaly_id=? AND status='pending'", (status, actor_id, note[:500], utc_now_iso(), anomaly_id))
            row = conn.execute("SELECT * FROM shopping_price_anomaly WHERE anomaly_id=?", (anomaly_id,)).fetchone()
        return dict(row) if row else None

    def product_detail(self, user_id: str, product_ref: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_product_record WHERE product_ref=? AND user_id=?", (product_ref, user_id)).fetchone()
            if not row:
                return None
            records = conn.execute("SELECT * FROM shopping_product_record WHERE user_id=? ORDER BY updated_at DESC LIMIT 500", (user_id,)).fetchall()
            review = conn.execute("SELECT * FROM shopping_review_report WHERE user_id=? AND product_ref=? ORDER BY created_at DESC LIMIT 1", (user_id, product_ref)).fetchone()
        product = json.loads(row["product_json"])
        offers, alternatives = [], []
        for candidate in records:
            if candidate["product_ref"] == product_ref:
                continue
            item = json.loads(candidate["product_json"])
            item["product_ref"] = candidate["product_ref"]
            if candidate["canonical_key"] == row["canonical_key"]:
                offers.append(item)
            elif candidate["family_key"] == row["family_key"] or (product.get("brand") and item.get("brand") == product.get("brand")):
                alternatives.append(item)
        history = self.price_history(str(product.get("url") or ""), user_id=user_id, limit=365) if str(product.get("url") or "").startswith(("http://", "https://")) else {"points": []}
        history["snapshots"] = history.get("points", [])
        review_evidence = _decode_json_columns(review, {"product_json": "product", "report_json": "report", "sources_json": "sources"}) if review else None
        with self._session() as conn:
            versions = [dict(item) for item in conn.execute("SELECT version,source,source_confidence,created_at FROM shopping_product_version WHERE product_ref=? AND user_id=? ORDER BY version DESC LIMIT 20", (product_ref, user_id)).fetchall()]
        return {"product_ref": product_ref, "product": product, "offers": offers[:20], "alternatives": alternatives[:8], "price_history": history, "review_evidence": review_evidence, "versions": versions, "updated_at": row["updated_at"]}

    def save_review_report(self, user_id: str, product: dict[str, Any], report: dict[str, Any], sources: list[str]) -> dict[str, Any]:
        product_ref = self.upsert_product_record(user_id, product)
        record = {"report_id": f"review_{uuid4().hex}", "user_id": user_id, "product_ref": product_ref, "product": product, "report": report, "sources": sources, "created_at": utc_now_iso()}
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_review_report(report_id,user_id,product_ref,product_json,report_json,sources_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (record["report_id"], user_id, product_ref, json.dumps(product, ensure_ascii=False), json.dumps(report, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), record["created_at"]))
        return record

    def list_saved_items(self, user_id: str, item_type: str | None = None, limit: int = 200, query_text: str | None = None, group_id: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM shopping_saved_item WHERE user_id=?", [user_id]
        if item_type:
            sql += " AND item_type=?"; params.append(item_type)
        if query_text:
            sql += " AND (label LIKE ? OR product_json LIKE ?)"; term = f"%{query_text[:80]}%"; params.extend([term, term])
        if group_id:
            sql += " AND saved_id IN (SELECT saved_id FROM shopping_saved_group_item WHERE user_id=? AND group_id=?)"; params.extend([user_id, group_id])
        sql += " ORDER BY updated_at DESC LIMIT ?"; params.append(max(1, min(limit, 500)))
        with self._session() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            groups = {row["saved_id"]: {"group_id": row["group_id"], "group_name": row["name"]} for row in conn.execute("SELECT i.saved_id,i.group_id,g.name FROM shopping_saved_group_item i JOIN shopping_saved_group g ON g.group_id=i.group_id WHERE i.user_id=?", (user_id,)).fetchall()}
        return [{**_decode_json_columns(row, {"product_json": "product"}), **groups.get(row["saved_id"], {"group_id": None, "group_name": None})} for row in rows]

    def delete_saved_item(self, user_id: str, saved_id: str) -> bool:
        with self._session() as conn:
            conn.execute("DELETE FROM shopping_saved_group_item WHERE saved_id=? AND user_id=?", (saved_id, user_id))
            return conn.execute("DELETE FROM shopping_saved_item WHERE saved_id=? AND user_id=?", (saved_id, user_id)).rowcount > 0

    def list_saved_groups(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT g.*,COUNT(i.saved_id) AS item_count FROM shopping_saved_group g LEFT JOIN shopping_saved_group_item i ON i.group_id=g.group_id AND i.user_id=g.user_id WHERE g.user_id=? GROUP BY g.group_id,g.user_id,g.name,g.created_at,g.updated_at ORDER BY g.updated_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_saved_group(self, user_id: str, name: str) -> dict[str, Any]:
        name = name.strip()[:40]
        if not name:
            raise ValueError("group name is required")
        now, group_id = utc_now_iso(), f"group_{uuid4().hex}"
        with self._session() as conn:
            old = conn.execute("SELECT * FROM shopping_saved_group WHERE user_id=? AND name=?", (user_id, name)).fetchone()
            if old:
                return dict(old)
            conn.execute("INSERT INTO shopping_saved_group(group_id,user_id,name,created_at,updated_at) VALUES(?,?,?,?,?)", (group_id, user_id, name, now, now))
        return {"group_id": group_id, "user_id": user_id, "name": name, "item_count": 0, "created_at": now, "updated_at": now}

    def bulk_saved_items(self, user_id: str, saved_ids: list[str], action: str, group_id: str | None = None) -> int:
        ids = list(dict.fromkeys(str(item) for item in saved_ids if str(item)))[:100]
        if not ids or action not in {"delete", "move"}:
            raise ValueError("invalid bulk saved action")
        placeholders = ",".join("?" for _ in ids)
        with self._session() as conn:
            owned = [row["saved_id"] for row in conn.execute(f"SELECT saved_id FROM shopping_saved_item WHERE user_id=? AND saved_id IN ({placeholders})", (user_id, *ids)).fetchall()]
            if action == "move":
                if not group_id or not conn.execute("SELECT 1 FROM shopping_saved_group WHERE user_id=? AND group_id=?", (user_id, group_id)).fetchone():
                    raise ValueError("saved group not found")
                now = utc_now_iso()
                for saved_id in owned:
                    conn.execute("INSERT INTO shopping_saved_group_item(user_id,saved_id,group_id,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,saved_id) DO UPDATE SET group_id=excluded.group_id,created_at=excluded.created_at", (user_id, saved_id, group_id, now))
                return len(owned)
            if owned:
                owned_placeholders = ",".join("?" for _ in owned)
                conn.execute(f"DELETE FROM shopping_saved_group_item WHERE user_id=? AND saved_id IN ({owned_placeholders})", (user_id, *owned))
                return int(conn.execute(f"DELETE FROM shopping_saved_item WHERE user_id=? AND saved_id IN ({owned_placeholders})", (user_id, *owned)).rowcount)
            return 0

    def user_dashboard(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            counts: dict[str, Any] = {}
            for key, table in (("reports", "shopping_decision_report"), ("monitors", "shopping_price_monitor"), ("purchases", "shopping_purchase_record"), ("unread", "shopping_notification")):
                suffix = " AND status='unread'" if key == "unread" else ""
                counts[key] = int(conn.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE user_id=?{suffix}", (user_id,)).fetchone()["total"])
            saved_rows = conn.execute("SELECT item_type,COUNT(*) AS total FROM shopping_saved_item WHERE user_id=? GROUP BY item_type", (user_id,)).fetchall()
            savings = conn.execute("SELECT COALESCE(SUM(value),0) AS total FROM shopping_business_event WHERE user_id=? AND event_type='purchase_confirmed'", (user_id,)).fetchone()
        counts.update({str(row["item_type"]): int(row["total"]) for row in saved_rows})
        return {**counts, "actual_savings": round(float(savings["total"] or 0), 2)}

    def list_content(self, status: str = "published", category: str | None = None, limit: int = 100, query_text: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM shopping_content", []
        if status != "all":
            sql += " WHERE status=?"; params.append(status)
        if category:
            sql += " AND" if " WHERE " in sql else " WHERE"; sql += " category=?"; params.append(category)
        if query_text:
            sql += " AND" if " WHERE " in sql else " WHERE"; sql += " (title LIKE ? OR summary LIKE ? OR body LIKE ?)"; term = f"%{query_text[:100]}%"; params.extend([term, term, term])
        sql += " ORDER BY COALESCE(published_at,updated_at) DESC LIMIT ?"; params.append(max(1, min(limit, 500)))
        with self._session() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def get_content(self, content_id: str, *, public_only: bool = True) -> dict[str, Any] | None:
        sql = "SELECT * FROM shopping_content WHERE content_id=?"
        params: list[Any] = [content_id]
        if public_only:
            sql += " AND status='published'"
        with self._session() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def related_content(self, content_id: str, limit: int = 4) -> list[dict[str, Any]]:
        item = self.get_content(content_id)
        if not item:
            return []
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_content WHERE status='published' AND content_id<>? AND (category=? OR content_type=?) ORDER BY COALESCE(published_at,updated_at) DESC LIMIT ?", (content_id, item["category"], item["content_type"], max(1, min(limit, 12)))).fetchall()
        return [dict(row) for row in rows]

    def save_content(self, payload: dict[str, Any], content_id: str | None = None) -> dict[str, Any]:
        now, content_id = utc_now_iso(), content_id or f"content_{uuid4().hex}"
        content_type = str(payload.get("content_type") or "guide")
        if content_type not in {"guide", "topic", "榜单", "case"}:
            raise ValueError("invalid content type")
        status = str(payload.get("status") or "draft")
        if status not in {"draft", "reviewing", "published", "offline"}:
            raise ValueError("invalid content status")
        title = str(payload.get("title") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        body = str(payload.get("body") or summary).strip()
        source_url = str(payload.get("source_url") or "").strip()
        if not title or not summary:
            raise ValueError("title and summary are required")
        if source_url and not source_url.startswith(("http://", "https://")):
            raise ValueError("source URL must use http or https")
        with self._session() as conn:
            old = conn.execute("SELECT created_at,published_at FROM shopping_content WHERE content_id=?", (content_id,)).fetchone()
            created = old["created_at"] if old else now
            published = old["published_at"] if old else None
            if status == "published" and not published:
                published = now
            conn.execute("""INSERT INTO shopping_content(content_id,content_type,title,summary,body,category,source_url,status,created_at,updated_at,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_id) DO UPDATE SET content_type=excluded.content_type,title=excluded.title,summary=excluded.summary,body=excluded.body,category=excluded.category,source_url=excluded.source_url,status=excluded.status,updated_at=excluded.updated_at,published_at=excluded.published_at""", (content_id, content_type, title, summary, body, str(payload.get("category") or "综合"), source_url, status, created, now, published))
            row = conn.execute("SELECT * FROM shopping_content WHERE content_id=?", (content_id,)).fetchone()
        return dict(row)

    def delete_content(self, content_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("DELETE FROM shopping_content WHERE content_id=?", (content_id,)).rowcount > 0

    def create_share(self, user_id: str, share_type: str, title: str, payload: dict[str, Any], expires_days: int = 30) -> dict[str, Any]:
        if share_type not in {"comparison", "report", "product"}:
            raise ValueError("invalid share type")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("share payload is required")
        now = datetime.now(timezone.utc)
        record = {"share_id": f"share_{uuid4().hex}", "share_token": uuid4().hex, "user_id": user_id, "share_type": share_type, "title": title.strip()[:120] or "ValuSee 分享", "payload": _public_share_payload(payload), "status": "active", "created_at": now.isoformat(), "expires_at": (now + timedelta(days=max(1, min(expires_days, 365)))).isoformat(), "revoked_at": None}
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_share(share_id,share_token,user_id,share_type,title,payload_json,status,created_at,expires_at,revoked_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (record["share_id"], record["share_token"], user_id, share_type, record["title"], json.dumps(record["payload"], ensure_ascii=False), record["status"], record["created_at"], record["expires_at"], None))
        return record

    def get_share(self, share_token: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_share WHERE share_token=?", (share_token,)).fetchone()
        if not row or row["status"] != "active" or _parse_or_now(row["expires_at"]) <= datetime.now(timezone.utc):
            return None
        result = _decode_json_columns(row, {"payload_json": "payload"})
        result.pop("user_id", None)
        return result

    def list_shares(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_share WHERE user_id=? ORDER BY created_at DESC LIMIT 200", (user_id,)).fetchall()
        return [_decode_json_columns(row, {"payload_json": "payload"}) for row in rows]

    def revoke_share(self, user_id: str, share_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("UPDATE shopping_share SET status='revoked',revoked_at=? WHERE share_id=? AND user_id=? AND status='active'", (utc_now_iso(), share_id, user_id)).rowcount > 0

    def save_comparison(self, user_id: str, name: str, products: list[dict[str, Any]], comparison_id: str | None = None) -> dict[str, Any]:
        now, comparison_id = utc_now_iso(), comparison_id or f"cmp_{uuid4().hex}"
        with self._session() as conn:
            owner = conn.execute("SELECT user_id,created_at FROM shopping_comparison_list WHERE comparison_id=?", (comparison_id,)).fetchone()
            if owner and owner["user_id"] != user_id:
                raise ValueError("comparison does not belong to this user")
            existing = owner
            created = existing["created_at"] if existing else now
            conn.execute("""INSERT INTO shopping_comparison_list(comparison_id,user_id,name,products_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(comparison_id) DO UPDATE SET name=excluded.name,products_json=excluded.products_json,status=excluded.status,updated_at=excluded.updated_at""",
                (comparison_id, user_id, name.strip() or "未命名对比", json.dumps(products, ensure_ascii=False), "active", created, now))
        for product in products:
            if isinstance(product, dict):
                self.upsert_product_record(user_id, product)
        return {"comparison_id": comparison_id, "user_id": user_id, "name": name.strip() or "未命名对比", "products": products, "status": "active", "created_at": created, "updated_at": now}

    def list_comparisons(self, user_id: str) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_comparison_list WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [_decode_json_columns(row, {"products_json": "products"}) for row in rows]

    def delete_comparison(self, user_id: str, comparison_id: str) -> bool:
        with self._session() as conn:
            return conn.execute("DELETE FROM shopping_comparison_list WHERE comparison_id=? AND user_id=?", (comparison_id, user_id)).rowcount > 0

    def save_report(self, user_id: str, task_id: str, goal: str, products: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
        record = {"report_id": f"report_{uuid4().hex}", "user_id": user_id, "task_id": task_id, "goal": goal, "products": products, "result": result, "created_at": utc_now_iso()}
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_decision_report(report_id,user_id,task_id,goal,products_json,result_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (record["report_id"], user_id, task_id, goal, json.dumps(products, ensure_ascii=False), json.dumps(result, ensure_ascii=False), record["created_at"]))
        for product in products:
            if isinstance(product, dict):
                self.upsert_product_record(user_id, product)
        return record

    def list_reports(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM shopping_decision_report WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 500)))).fetchall()
        return [_decode_json_columns(row, {"products_json": "products", "result_json": "result"}) for row in rows]

    def create_feedback(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        record = {"feedback_id": f"feedback_{uuid4().hex}", "user_id": user_id, "feedback_type": str(payload.get("feedback_type") or "other"), "target_type": str(payload.get("target_type") or "report"), "target_id": str(payload.get("target_id") or "") or None, "content": str(payload.get("content") or "").strip(), "evidence": payload.get("evidence") or {}, "status": "open", "created_at": now, "updated_at": now}
        if not record["content"]:
            raise ValueError("feedback content is required")
        with self._session() as conn:
            conn.execute("INSERT INTO shopping_feedback(feedback_id,user_id,feedback_type,target_type,target_id,content,evidence_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (record["feedback_id"], user_id, record["feedback_type"], record["target_type"], record["target_id"], record["content"], json.dumps(record["evidence"], ensure_ascii=False), record["status"], now, now))
        self.record_business_event(user_id, "feedback_submitted", record["feedback_id"], idempotency_key=f"feedback:{record['feedback_id']}")
        return record

    def list_feedback(self, user_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM shopping_feedback", []
        if user_id:
            sql += " WHERE user_id=?"; params.append(user_id)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(max(1, min(limit, 1000)))
        with self._session() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_decode_json_columns(row, {"evidence_json": "evidence"}) for row in rows]

    def update_feedback_status(self, feedback_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"open", "reviewing", "resolved", "rejected"}:
            raise ValueError("invalid feedback status")
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE shopping_feedback SET status=?,updated_at=? WHERE feedback_id=?",
                (status, utc_now_iso(), feedback_id),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM shopping_feedback WHERE feedback_id=?", (feedback_id,)).fetchone()
        result = _decode_json_columns(row, {"evidence_json": "evidence"})
        if status == "resolved":
            self.record_business_event(str(result["user_id"]), "feedback_resolved", feedback_id, idempotency_key=f"feedback-resolved:{feedback_id}")
        return result

    def record_business_event(self, user_id: str, event_type: str, reference_id: str | None = None, value: float = 0.0, metadata: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any] | None:
        record = {"event_id": f"evt_{uuid4().hex}", "user_id": user_id, "event_type": event_type, "reference_id": reference_id, "value": round(float(value), 2), "metadata": metadata or {}, "idempotency_key": idempotency_key or f"event:{uuid4().hex}", "created_at": utc_now_iso()}
        with self._session() as conn:
            try:
                conn.execute("INSERT INTO shopping_business_event(event_id,user_id,event_type,reference_id,value,metadata_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?)", (record["event_id"], user_id, event_type, reference_id, record["value"], json.dumps(record["metadata"], ensure_ascii=False), record["idempotency_key"], record["created_at"]))
            except Exception as exc:
                if is_integrity_error(exc):
                    return None
                raise
        return record

    def business_metrics(self, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        with self._session() as conn:
            rows = conn.execute("SELECT event_type,value,metadata_json FROM shopping_business_event WHERE created_at>=?", (since,)).fetchall()
        counts: dict[str, int] = {}
        latencies: list[int] = []
        savings = 0.0
        for row in rows:
            event_type = str(row["event_type"])
            counts[event_type] = counts.get(event_type, 0) + 1
            if event_type == "purchase_confirmed":
                savings += float(row["value"] or 0)
            if event_type == "analysis_completed":
                latency = int((json.loads(row["metadata_json"] or "{}") or {}).get("latency_ms") or 0)
                if latency >= 0:
                    latencies.append(latency)
        latencies.sort()
        started, completed = counts.get("analysis_started", 0), counts.get("analysis_completed", 0)
        monitors, reached = counts.get("monitor_created", 0), counts.get("monitor_target_reached", 0)
        feedback, resolved = counts.get("feedback_submitted", 0), counts.get("feedback_resolved", 0)
        return {
            "period_days": days, "events": counts,
            "analysis_completion_rate": round(completed / started, 4) if started else 0.0,
            "recommendation_acceptance_rate": round(counts.get("recommendation_accepted", 0) / completed, 4) if completed else 0.0,
            "monitor_conversion_rate": round(reached / monitors, 4) if monitors else 0.0,
            "feedback_resolution_rate": round(resolved / feedback, 4) if feedback else 0.0,
            "actual_savings": round(savings, 2),
            "analysis_p95_latency_ms": latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95)))] if latencies else 0,
        }

    def save_notification_preference(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        record = {"user_id": user_id, "email_enabled": bool(payload.get("email_enabled", True)), "in_app_enabled": bool(payload.get("in_app_enabled", True)), "quiet_start": str(payload.get("quiet_start") or "") or None, "quiet_end": str(payload.get("quiet_end") or "") or None, "updated_at": now}
        with self._session() as conn:
            old = conn.execute("SELECT created_at FROM shopping_notification_preference WHERE user_id=?", (user_id,)).fetchone()
            created = old["created_at"] if old else now
            conn.execute("""INSERT INTO shopping_notification_preference(user_id,email_enabled,in_app_enabled,quiet_start,quiet_end,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET email_enabled=excluded.email_enabled,in_app_enabled=excluded.in_app_enabled,quiet_start=excluded.quiet_start,quiet_end=excluded.quiet_end,updated_at=excluded.updated_at""",
                (user_id, 1 if record["email_enabled"] else 0, 1 if record["in_app_enabled"] else 0, record["quiet_start"], record["quiet_end"], created, now))
        return {**record, "created_at": created}

    def get_notification_preference(self, user_id: str) -> dict[str, Any]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM shopping_notification_preference WHERE user_id=?", (user_id,)).fetchone()
        return {**dict(row), "email_enabled": bool(row["email_enabled"]), "in_app_enabled": bool(row["in_app_enabled"])} if row else {"user_id": user_id, "email_enabled": True, "in_app_enabled": True, "quiet_start": None, "quiet_end": None}

    def update_user_monitor(self, user_id: str, monitor_id: str, *, target_price: float | None = None, status: str | None = None) -> dict[str, Any] | None:
        monitor = self.get_monitor(monitor_id)
        if not monitor or monitor["user_id"] != user_id:
            return None
        if status and status not in {"watching", "paused"}:
            raise ValueError("status must be watching or paused")
        target = round(float(target_price), 2) if target_price is not None else monitor["target_price"]
        if target <= 0:
            raise ValueError("target_price must be greater than zero")
        next_status = status or monitor["status"]
        with self._session() as conn:
            conn.execute("UPDATE shopping_price_monitor SET target_price=?,status=?,updated_at=?,last_message=? WHERE monitor_id=? AND user_id=?",
                (target, next_status, utc_now_iso(), _monitor_message(monitor["current_final_price"], target), monitor_id, user_id))
        return self.get_monitor(monitor_id)

    def delete_user_monitor(self, user_id: str, monitor_id: str) -> bool:
        with self._session() as conn:
            found = conn.execute("SELECT 1 FROM shopping_price_monitor WHERE monitor_id=? AND user_id=?", (monitor_id, user_id)).fetchone()
            if not found: return False
            conn.execute("DELETE FROM shopping_price_check WHERE monitor_id=?", (monitor_id,))
            conn.execute("DELETE FROM shopping_monitor_preference WHERE monitor_id=? AND user_id=?", (monitor_id, user_id))
            return conn.execute("DELETE FROM shopping_price_monitor WHERE monitor_id=? AND user_id=?", (monitor_id, user_id)).rowcount > 0


def _decode_json_columns(row: Any, mapping: dict[str, str]) -> dict[str, Any]:
    result = dict(row)
    for source, target in mapping.items():
        raw = result.pop(source, None)
        result[target] = json.loads(raw) if raw else ([] if target == "products" else {})
    return result


def _risk_rule_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": str(row["rule_id"]),
        "code": str(row["code"]),
        "name": str(row["name"]),
        "field_name": str(row["field_name"]),
        "pattern": str(row["pattern"]).lower(),
        "severity": str(row["severity"]),
        "action": str(row["action"]),
    }


def _public_share_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"user_id", "email", "password", "access_token", "verification_token", "reset_token", "notes"}

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items() if str(key).lower() not in blocked}
        if isinstance(value, list):
            return [clean(item) for item in value[:100]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    cleaned = clean(payload)
    encoded = json.dumps(cleaned, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 512_000:
        raise ValueError("share payload is too large")
    return cleaned


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


def _row_to_monitor(row: Any) -> dict[str, Any]:
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


def _row_to_check(row: Any) -> dict[str, Any]:
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


def _row_to_purchase(row: Any) -> dict[str, Any]:
    return {
        "purchase_id": row["purchase_id"],
        "user_id": row["user_id"],
        "product": json.loads(row["product_json"]),
        "paid_price": float(row["paid_price"]),
        "platform": row["platform"] or "",
        "store_name": row["store_name"] or "",
        "purchased_at": row["purchased_at"],
        "price_protection_deadline": row["price_protection_deadline"],
        "return_deadline": row["return_deadline"],
        "warranty_deadline": row["warranty_deadline"],
        "consumable_reminder_at": row["consumable_reminder_at"],
        "status": row["status"],
        "reminders": json.loads(row["reminders_json"]),
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _utc_plus_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_or_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deadline(start: datetime, *, days: int | None) -> str | None:
    if not days:
        return None
    return (start + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_purchase_reminders(
    *,
    price_protection_deadline: str | None,
    return_deadline: str | None,
    warranty_deadline: str | None,
    consumable_reminder_at: str | None,
) -> list[dict[str, Any]]:
    reminders = []
    if price_protection_deadline:
        reminders.append({"type": "price_protection", "title": "保价截止提醒", "remind_at": price_protection_deadline})
    if return_deadline:
        reminders.append({"type": "return_deadline", "title": "无理由退货截止提醒", "remind_at": return_deadline})
    if warranty_deadline:
        reminders.append({"type": "warranty_deadline", "title": "保修到期提醒", "remind_at": warranty_deadline})
    if consumable_reminder_at:
        reminders.append({"type": "consumable", "title": "耗材更换提醒", "remind_at": consumable_reminder_at})
    return reminders


def _monitor_message(final_price: float, target_price: float) -> str:
    if final_price <= target_price:
        return f"已达到目标价：当前到手价 {final_price:.0f} 元，目标价 {target_price:.0f} 元。"
    return f"继续观察：当前到手价 {final_price:.0f} 元，距离目标价还差 {final_price - target_price:.0f} 元。"


def _notification_target(kind: str) -> str:
    if kind in {"price_reached", "price_drop", "monitor", "price_confirmation_required", "recapture_required"}:
        return "/?view=monitors"
    if kind in {"price_protection", "return_deadline", "warranty_deadline", "after_sales"}:
        return "/?view=purchases"
    return "/?view=messages"


def _source_confidence(source: str) -> float:
    value = source.strip().lower()
    if any(token in value for token in ("official_api", "open_platform", "affiliate_api")):
        return 0.98
    if "extension" in value:
        return 0.85
    if any(token in value for token in ("ocr", "image", "upload")):
        return 0.65
    if any(token in value for token in ("manual", "user_input", "user")):
        return 0.55
    return 0.5


def _validate_llm_base_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Base URL 必须是 HTTPS 地址")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Base URL 不允许指向本机地址")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)]
        except OSError as exc:
            raise ValueError("Base URL 域名无法解析") from exc
    if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved for address in addresses):
        raise ValueError("Base URL 不允许指向内网地址")


shopping_store = ShoppingStore()


def _validate_llm_model(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value):
        raise ValueError("模型名称格式无效")
    return value
