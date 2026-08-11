from pathlib import Path

from fastapi.testclient import TestClient

from app.auth.service import AuthStore
from app.main import app


def test_email_code_is_hashed_single_use_and_rate_limited(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "registration-code.db")
    code = store.issue_email_code("Buyer@Example.com", "register")

    with store._session() as connection:
        row = connection.execute(
            "SELECT code_hash FROM valuesee_email_code WHERE email=? AND purpose=?",
            ("buyer@example.com", "register"),
        ).fetchone()
    assert row and row["code_hash"] != code
    assert code not in (tmp_path / "registration-code.db").read_bytes().decode("latin1")

    try:
        store.issue_email_code("buyer@example.com", "register")
    except ValueError as exc:
        assert "频繁" in str(exc)
    else:
        raise AssertionError("registration code cooldown must be enforced")

    assert store.consume_email_code("buyer@example.com", "register", "000000") is False
    assert store.consume_email_code("buyer@example.com", "register", code) is True
    assert store.consume_email_code("buyer@example.com", "register", code) is False


def test_registration_requires_code_and_matching_passwords(monkeypatch, tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "verified-registration.db")
    monkeypatch.setattr("app.api.routes.auth_store", store)
    monkeypatch.setattr("app.auth.service.auth_store", store)
    monkeypatch.setattr("app.api.routes.send_transactional_email", lambda *_args, **_kwargs: True)
    client = TestClient(app)

    issued = client.post(
        "/api/v1/auth/register/code/request",
        json={"email": "verified@example.com"},
    )
    assert issued.status_code == 200
    code = issued.json()["verification_code"]
    mismatch = client.post(
        "/api/v1/auth/register",
        json={
            "email": "verified@example.com",
            "password": "strong-password",
            "confirm_password": "different-password",
            "verification_code": code,
            "display_name": "Verified",
        },
    )
    assert mismatch.status_code == 422

    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "verified@example.com",
            "password": "strong-password",
            "confirm_password": "strong-password",
            "verification_code": code,
            "display_name": "Verified",
        },
    )
    assert registered.status_code == 200
    assert registered.json()["user"]["email_verified"] is True
    assert client.post(
        "/api/v1/auth/register",
        json={
            "email": "verified@example.com",
            "password": "strong-password",
            "confirm_password": "strong-password",
            "verification_code": code,
        },
    ).status_code == 422


def test_registration_code_is_removed_when_email_delivery_fails(monkeypatch, tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "failed-registration-email.db")
    monkeypatch.setattr("app.api.routes.auth_store", store)
    monkeypatch.setattr("app.api.routes.send_transactional_email", lambda *_args, **_kwargs: False)

    response = TestClient(app).post(
        "/api/v1/auth/register/code/request",
        json={"email": "delivery@example.com"},
    )

    assert response.status_code == 503
    with store._session() as connection:
        assert connection.execute("SELECT 1 FROM valuesee_email_code").fetchone() is None


def test_password_reset_confirmation_mismatch_does_not_consume_link(monkeypatch, tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "reset-confirmation.db")
    user = store.register("reset@example.com", "old-password", "Reset")
    token = store.create_action_token(user["user_id"], "reset_password")
    monkeypatch.setattr("app.api.routes.auth_store", store)
    client = TestClient(app)

    mismatch = client.post(
        "/api/v1/auth/password/reset/confirm",
        json={
            "token": token,
            "new_password": "new-password",
            "confirm_password": "different-password",
        },
    )
    assert mismatch.status_code == 422
    completed = client.post(
        "/api/v1/auth/password/reset/confirm",
        json={
            "token": token,
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
    )
    assert completed.status_code == 200
    assert store.authenticate("reset@example.com", "new-password") is not None
