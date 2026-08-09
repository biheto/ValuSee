from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore
from app.shopping.store import ShoppingStore


def _purchase(store: ShoppingStore, user_id: str = "u1") -> dict[str, object]:
    return store.create_purchase(
        user_id=user_id, product={"title": "Monitor", "price": 100}, paid_price=90,
        platform="manual", store_name="Store", purchased_at=None, price_protection_days=7,
        return_days=7, warranty_months=12, consumable_cycle_days=None, notes="",
    )


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


def test_purchase_attachments_are_owner_scoped():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        purchase = _purchase(store)
        metadata = {"attachment_type": "invoice", "original_name": "invoice.pdf", "content_type": "application/pdf", "size_bytes": 12, "sha256": "abc", "storage_backend": "local", "storage_key": "data/attachments/test.pdf"}
        attachment = store.create_purchase_attachment("u1", str(purchase["purchase_id"]), metadata)
        assert store.list_purchase_attachments("u1", str(purchase["purchase_id"]))[0]["attachment_id"] == attachment["attachment_id"]
        assert store.list_purchase_attachments("u2", str(purchase["purchase_id"])) == []
        assert store.get_purchase_attachment("u2", attachment["attachment_id"]) is None
        try:
            store.create_purchase_attachment("u2", str(purchase["purchase_id"]), metadata)
        except ValueError:
            pass
        else:
            raise AssertionError("another user must not attach files to a purchase")


def test_support_ticket_conversation_is_scoped_and_stateful():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        purchase = _purchase(store)
        ticket = store.create_support_ticket("u1", {"purchase_id": purchase["purchase_id"], "category": "price_protection", "subject": "Need help", "content": "Price dropped"})
        assert ticket["status"] == "open" and ticket["messages"][0]["actor_role"] == "user"
        assert store.get_support_ticket("u2", ticket["ticket_id"]) is None
        try:
            store.reply_support_ticket("u2", ticket["ticket_id"], "Hijack")
        except ValueError:
            pass
        else:
            raise AssertionError("another user must not reply to a ticket")
        admin_reply = store.reply_support_ticket("admin", ticket["ticket_id"], "Please attach the invoice", admin=True, status="waiting_user")
        assert admin_reply["status"] == "waiting_user" and len(admin_reply["messages"]) == 2
        user_reply = store.reply_support_ticket("u1", ticket["ticket_id"], "Attached")
        assert user_reply["status"] == "open" and len(user_reply["messages"]) == 3


def test_price_protection_claim_is_scoped_and_records_savings_once():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "valuesee-test.db")
        purchase = _purchase(store)
        claim = store.save_price_protection_claim("u1", str(purchase["purchase_id"]), {"status": "succeeded", "approved_amount": 20, "requested_amount": 20})
        assert claim["evidence_source"] == "user_reported"
        assert store.list_price_protection_claims("u1", str(purchase["purchase_id"]))[0]["approved_amount"] == 20
        assert store.list_price_protection_claims("u2", str(purchase["purchase_id"])) == []
        store.save_price_protection_claim("u1", str(purchase["purchase_id"]), {"claim_id": claim["claim_id"], "status": "succeeded", "approved_amount": 20, "requested_amount": 20})
        assert store.list_savings("u1")["total"] == 30
        try:
            store.save_price_protection_claim("u2", str(purchase["purchase_id"]), {"status": "submitted", "requested_amount": 20})
        except ValueError:
            pass
        else:
            raise AssertionError("another user must not create a claim")


def test_account_export_and_delete_cover_support_conversation():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "valuesee-test.db"
        store, auth = ShoppingStore(path), AuthStore(path)
        user = auth.register("support-export@example.com", "strong-password", "Support")
        ticket = store.create_support_ticket(user["user_id"], {"subject": "Export me", "content": "Conversation body"})
        store.reply_support_ticket("admin", ticket["ticket_id"], "Admin response", admin=True)
        exported = auth.export_account(user["user_id"])
        assert len(exported["support_tickets"]) == 1 and len(exported["support_messages"]) == 2
        auth.delete_account(user["user_id"])
        assert store.list_support_tickets(user["user_id"]) == []
        with store._session() as conn:
            assert conn.execute("SELECT 1 FROM shopping_support_message WHERE ticket_id=?", (ticket["ticket_id"],)).fetchone() is None
