from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.auth.service import AuthStore, _totp
from app.main import app


def test_email_verification_token_is_single_use():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("buyer@example.com", "old-password", "Buyer")
        token = store.create_action_token(user["user_id"], "verify_email", ttl_minutes=30)
        verified = store.verify_email(token)
        assert verified and verified["email_verified"] is True
        assert store.verify_email(token) is None


def test_password_reset_replaces_password_and_consumes_token():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("buyer@example.com", "old-password", "Buyer")
        token = store.create_action_token(user["user_id"], "reset_password", ttl_minutes=30)
        assert store.reset_password(token, "new-password") is True
        assert store.authenticate("buyer@example.com", "old-password") is None
        assert store.authenticate("buyer@example.com", "new-password") is not None
        assert store.reset_password(token, "another-password") is False


def test_family_owner_can_manage_member_role_and_members_cannot():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        owner = store.register("owner@example.com", "owner-password", "Owner")
        member = store.register("member@example.com", "member-password", "Member")
        family = store.create_family(owner["user_id"], "家庭")
        store.invite_family_member(owner["user_id"], family["family_id"], member["email"])
        updated = store.set_family_member_role(owner["user_id"], family["family_id"], member["user_id"], "editor")
        assert updated["role"] == "editor"
        assert len(store.list_family_members(member["user_id"], family["family_id"])) == 2
        try:
            store.remove_family_member(member["user_id"], family["family_id"], owner["user_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("non-owner must not manage family members")


def test_sessions_can_be_listed_and_revoked():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("session@example.com", "strong-password", "Session")
        token = store.create_session(user["user_id"], "Chrome on Windows", "127.0.0.1")
        sessions = store.list_sessions(user["user_id"], token)
        assert len(sessions) == 1 and sessions[0]["current"] is True
        assert store.validate_session(sessions[0]["session_id"], token) is True
        assert store.revoke_session("another-user", sessions[0]["session_id"]) is False
        assert store.revoke_session(user["user_id"], sessions[0]["session_id"]) is True
        assert store.validate_session(sessions[0]["session_id"], token) is False


def test_password_reset_revokes_existing_sessions():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("reset-session@example.com", "old-password", "Reset")
        token = store.create_session(user["user_id"])
        action = store.create_action_token(user["user_id"], "reset_password")
        assert store.reset_password(action, "new-password") is True
        session_id = store.list_sessions(user["user_id"])[0]["session_id"]
        assert store.validate_session(session_id, token) is False


def test_membership_defaults_to_free_and_upgrade_is_pending():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("member-plan@example.com", "strong-password", "Plan")
        status = store.subscription_status(user["user_id"])
        assert status["plan_code"] == "free" and status["limits"]["active_monitors"] == 3
        first = store.request_upgrade(user["user_id"], "pro")
        second = store.request_upgrade(user["user_id"], "pro")
        assert first["status"] == "pending" and second["request_id"] == first["request_id"]


def test_billing_order_never_implies_payment_without_provider():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("billing@example.com", "strong-password", "Billing")
        first = store.create_billing_order(user["user_id"], "pro", "monthly")
        second = store.create_billing_order(user["user_id"], "pro", "monthly")
        assert first["order_id"] == second["order_id"]
        assert first["status"] == "pending_external_payment" and first["amount"] == 19
        assert store.subscription_status(user["user_id"])["plan_code"] == "free"
        cancelled = store.cancel_billing_order(user["user_id"], first["order_id"])
        assert cancelled and cancelled["status"] == "cancelled"
        assert store.list_billing_orders("another-user") == []


def test_admin_totp_enrollment_revokes_old_sessions_and_recovery_codes_are_single_use():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("admin@example.com", "strong-password", "Admin")
        old_token = store.create_session(user["user_id"])
        setup = store.setup_admin_mfa(user["user_id"], user["email"])
        assert setup["secret"] not in (Path(tmp) / "auth.db").read_bytes().decode("latin1")
        assert store.confirm_admin_mfa(user["user_id"], _totp(setup["secret"])) is True
        old_session = store.list_sessions(user["user_id"])[0]
        assert store.validate_session(old_session["session_id"], old_token) is False
        assert store.admin_mfa_status(user["user_id"])["enabled"] is True

        recovery = setup["recovery_codes"][0]
        assert store.verify_admin_mfa(user["user_id"], recovery) is True
        assert store.verify_admin_mfa(user["user_id"], recovery) is False


def test_admin_can_disable_mfa_with_current_password_after_verified_login():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("admin-disable@example.com", "strong-password", "Admin")
        setup = store.setup_admin_mfa(user["user_id"], user["email"])
        assert store.confirm_admin_mfa(user["user_id"], _totp(setup["secret"])) is True
        assert store.disable_admin_mfa(user["user_id"], password="wrong-password") is False
        assert store.admin_mfa_status(user["user_id"])["enabled"] is True
        assert store.disable_admin_mfa(user["user_id"], password="strong-password") is True
        assert store.admin_mfa_status(user["user_id"])["enabled"] is False


def test_admin_api_requires_mfa_after_enrollment(monkeypatch, tmp_path):
    store = AuthStore(tmp_path / "admin-mfa.db")
    user = store.register("mfa-admin@example.com", "strong-password", "MFA Admin")
    token = store.create_session(user["user_id"])
    monkeypatch.setenv("VALUSee_ADMIN_EMAILS", user["email"])
    monkeypatch.setattr("app.api.routes.auth_store", store)
    monkeypatch.setattr("app.auth.service.auth_store", store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    setup = client.post("/api/v1/admin/security/mfa/setup", headers=headers).json()
    confirmed = client.post("/api/v1/admin/security/mfa/confirm", headers=headers, json={"code": _totp(setup["secret"])})
    assert confirmed.status_code == 200
    verified_token = confirmed.json()["access_token"]
    assert client.get("/api/v1/admin/overview", headers=headers).status_code == 401
    assert client.get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {verified_token}"}).status_code == 200

    assert client.post("/api/v1/auth/login", json={"email": user["email"], "password": "strong-password"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": user["email"], "password": "strong-password", "mfa_code": _totp(setup["secret"])})
    assert login.status_code == 200 and login.json()["mfa_verified"] is True
    disabled = client.request(
        "DELETE",
        "/api/v1/admin/security/mfa",
        headers={"Authorization": f"Bearer {verified_token}"},
        json={"password": "strong-password"},
    )
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False


def test_free_plan_entitlements_are_enforced_against_real_usage():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        user = store.register("quota@example.com", "strong-password", "Quota")
        with store._session() as conn:
            conn.execute("CREATE TABLE shopping_price_monitor(user_id TEXT,status TEXT)")
            for _ in range(3):
                conn.execute("INSERT INTO shopping_price_monitor VALUES(?,?)", (user["user_id"], "watching"))
        usage = store.entitlement_usage(user["user_id"])
        assert usage["active_monitors"] == 3
        try:
            store.require_entitlement(user["user_id"], "active_monitors")
        except ValueError as exc:
            assert "额度" in str(exc)
        else:
            raise AssertionError("free monitor quota must be enforced")


def test_export_hides_session_secrets_and_owner_deletion_cleans_family():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "auth.db")
        owner = store.register("delete-owner@example.com", "strong-password", "Owner")
        member = store.register("delete-member@example.com", "strong-password", "Member")
        store.create_session(owner["user_id"])
        family = store.create_family(owner["user_id"], "Household")
        store.invite_family_member(owner["user_id"], family["family_id"], member["email"])
        exported = store.export_account(owner["user_id"])
        assert exported["sessions"] and "token_hash" not in exported["sessions"][0]
        store.delete_account(owner["user_id"])
        with store._session() as conn:
            assert conn.execute("SELECT 1 FROM valuesee_family_member WHERE family_id=?", (family["family_id"],)).fetchone() is None
