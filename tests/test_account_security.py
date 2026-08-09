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
