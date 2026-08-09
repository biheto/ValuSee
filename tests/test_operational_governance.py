from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore
from app.shopping.store import ShoppingStore


def test_campaign_publication_window_and_crud():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "operations.db")
        draft = store.save_campaign({"name": "Draft", "title": "Internal", "status": "draft"})
        live = store.save_campaign({"name": "Launch", "title": "Visible", "summary": "Source-aware", "status": "published", "starts_at": "2020-01-01T00:00:00+00:00", "ends_at": "2099-01-01T00:00:00+00:00"})
        ended = store.save_campaign({"name": "Ended", "title": "Old", "status": "published", "ends_at": "2020-01-01T00:00:00+00:00"})
        assert [item["campaign_id"] for item in store.list_campaigns(public_only=True)] == [live["campaign_id"]]
        assert store.delete_campaign(draft["campaign_id"]) is True
        assert store.delete_campaign(ended["campaign_id"]) is True
        try:
            store.save_campaign({"name": "Unsafe", "title": "Unsafe", "target_url": "javascript:alert(1)"})
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe campaign protocols must be rejected")


def test_governed_risk_rules_match_fields_and_are_audited():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "operations.db")
        rule = store.save_risk_rule({"code": "refurbished", "name": "翻新风险", "field_name": "title", "pattern": "翻新", "severity": "high", "action": "block"})
        matches = store.evaluate_risk_rules({"title": "官方翻新耳机"})
        assert matches and matches[0]["severity"] == "high" and matches[0]["action"] == "block"
        audit = store.record_admin_audit("admin", "risk_rule.save", "risk_rule", rule["rule_id"], {"enabled": True})
        assert store.list_admin_audits()[0]["audit_id"] == audit["audit_id"]
        assert store.delete_risk_rule(rule["rule_id"]) is True


def test_suspending_user_revokes_all_sessions_and_upgrade_is_governed():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "operations.db")
        user = store.register("operations@example.com", "strong-password", "Operations")
        token = store.create_session(user["user_id"])
        session = store.list_sessions(user["user_id"])[0]
        upgrade = store.request_upgrade(user["user_id"], "pro")
        assert store.update_upgrade_request(upgrade["request_id"], "contacted")["status"] == "contacted"
        assert store.update_user_status(user["user_id"], "suspended")["status"] == "suspended"
        assert store.validate_session(session["session_id"], token) is False
