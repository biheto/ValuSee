from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore


def test_profile_localization_avatar_metadata_and_audit_are_owner_scoped():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "profile.db")
        user = store.register("profile@example.com", "strong-password", "Before")
        other = store.register("other@example.com", "strong-password", "Other")
        profile = store.update_account_profile(user["user_id"], {"display_name": "After", "bio": "Careful buyer", "locale": "en-US", "currency": "USD"})
        assert profile["display_name"] == "After" and profile["currency"] == "USD"
        avatar = store.set_account_avatar(user["user_id"], {"backend": "local", "key": "data/attachments/avatar.png", "content_type": "image/png", "sha256": "abc"})
        assert avatar["avatar_url"] == "/api/v1/auth/profile/avatar"
        assert store.account_avatar(other["user_id"]) is None
        assert [item["action"] for item in store.list_user_audits(user["user_id"])] == ["avatar.updated", "profile.updated"]
        assert store.list_user_audits(other["user_id"]) == []
        assert store.account_bindings(user["user_id"])[0]["status"] == "pending"


def test_profile_rejects_unsupported_locale_and_currency():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "profile.db")
        user = store.register("profile@example.com", "strong-password", "User")
        try:
            store.update_account_profile(user["user_id"], {"display_name": "User", "locale": "invalid", "currency": "BTC"})
        except ValueError:
            pass
        else:
            raise AssertionError("unsupported locale and currency must be rejected")
