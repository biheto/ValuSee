from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore


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
