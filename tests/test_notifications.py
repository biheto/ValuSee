from unittest.mock import MagicMock, patch

from app.shopping.notifications import deliver_notification


def test_notification_stays_in_app_when_external_channels_are_unconfigured():
    with patch.dict("os.environ", {}, clear=True):
        assert deliver_notification({"user_id": "u1", "title": "降价", "message": "已到目标价"}) == "in_app"


def test_notification_can_deliver_email_without_losing_in_app_record():
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    with patch.dict("os.environ", {
        "VALUSee_SMTP_HOST": "smtp.example.com", "VALUSee_SMTP_PORT": "465",
        "VALUSee_SMTP_USERNAME": "notice@example.com", "VALUSee_SMTP_PASSWORD": "auth-code",
        "VALUSee_SMTP_FROM": "notice@example.com", "VALUSee_SMTP_SSL": "true",
    }, clear=True), patch("app.auth.service.auth_store.get_user", return_value={"email": "buyer@example.com"}), patch("smtplib.SMTP_SSL", return_value=smtp):
        delivery = deliver_notification({"user_id": "u1", "title": "降价提醒", "message": "商品已到目标价"})
    assert delivery == "in_app+email"
    smtp.send_message.assert_called_once()


def test_notification_preferences_can_disable_user_facing_delivery():
    with patch.dict("os.environ", {}, clear=True):
        delivery = deliver_notification(
            {"user_id": "u1", "title": "Price", "message": "Reached"},
            {"in_app_enabled": False, "email_enabled": False},
        )
    assert delivery == "audit_only"


def test_quiet_hours_defer_external_delivery():
    with patch.dict("os.environ", {"VALUSee_SMTP_HOST": "smtp.example.com"}, clear=True), patch(
        "app.shopping.notifications._deliver_email"
    ) as email:
        delivery = deliver_notification(
            {"user_id": "u1", "title": "Price", "message": "Reached"},
            {"in_app_enabled": True, "email_enabled": True, "quiet_start": "00:00", "quiet_end": "23:59"},
        )
    assert delivery == "in_app+quiet_deferred"
    email.assert_not_called()
