import io
import socket
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core.url_security import validate_public_https_url
from app.core.config import validate_production_config
from app.main import app
from app.marketplace.installer import _safe_extract
from app.shopping.vision import inspect_product_image


def test_public_url_validator_blocks_credentials_http_private_and_unapproved_hosts(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    allowed = {"github.com"}
    assert validate_public_https_url("https://github.com/org/repo", allowed_hosts=allowed)
    with pytest.raises(ValueError):
        validate_public_https_url("http://github.com/org/repo", allowed_hosts=allowed)
    with pytest.raises(ValueError):
        validate_public_https_url("https://user:secret@github.com/repo", allowed_hosts=allowed)
    with pytest.raises(ValueError):
        validate_public_https_url("https://example.com/repo", allowed_hosts=allowed)

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        validate_public_https_url("https://github.com/org/repo", allowed_hosts=allowed)


def test_marketplace_zip_cannot_escape_extraction_root(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    payload.seek(0)
    with zipfile.ZipFile(payload) as archive, pytest.raises(ValueError):
        _safe_extract(archive, tmp_path / "package")
    assert not (tmp_path / "outside.txt").exists()


def test_marketplace_zip_rejects_excessive_uncompressed_size(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        info = zipfile.ZipInfo("large.bin")
        info.file_size = 51 * 1024 * 1024
        archive.writestr(info, b"x")
    payload.seek(0)
    with zipfile.ZipFile(payload) as archive:
        archive.filelist[0].file_size = 51 * 1024 * 1024
        with pytest.raises(ValueError, match="too large"):
            _safe_extract(archive, tmp_path / "package")


def test_product_image_rejects_spoofed_mime_type():
    with pytest.raises(ValueError, match="声明类型"):
        inspect_product_image(b"not-a-real-image", "image/png", "fake.png")


def test_marketplace_mutations_require_authentication_in_production(monkeypatch):
    monkeypatch.setattr("app.api.routes.settings.app_env", "production")
    client = TestClient(app)
    assert client.get("/api/v1/marketplace/installs").status_code == 401
    assert client.post("/api/v1/marketplace/preview", json={"source_url": "builtin://x"}).status_code == 401
    assert client.post("/api/v1/marketplace/install", json={"source_url": "builtin://x"}).status_code == 401
    assert client.delete("/api/v1/marketplace/packages/x").status_code == 401


def test_production_config_rejects_weak_secrets_and_accepts_explicit_tls_origin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VALUSee_JWT_SECRET", "weak")
    monkeypatch.setenv("VALUSee_METRICS_TOKEN", "also-weak")
    monkeypatch.setenv("VALUSee_MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setenv("VALUSee_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("ALLOWED_HOSTS", "shop.example.com")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://shop.example.com")
    monkeypatch.setenv("VALUSee_PUBLIC_BASE_URL", "https://shop.example.com")
    with pytest.raises(RuntimeError, match="VALUSee_JWT_SECRET"):
        validate_production_config()

    monkeypatch.setenv("VALUSee_JWT_SECRET", "j" * 40)
    monkeypatch.setenv("VALUSee_METRICS_TOKEN", "m" * 32)
    monkeypatch.setenv("VALUSee_MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    validate_production_config()


def test_production_config_rejects_wildcards_and_non_tls_origins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VALUSee_JWT_SECRET", "j" * 40)
    monkeypatch.setenv("VALUSee_METRICS_TOKEN", "m" * 32)
    monkeypatch.setenv("VALUSee_MFA_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setenv("VALUSee_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("VALUSee_PUBLIC_BASE_URL", "https://shop.example.com")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://shop.example.com")
    with pytest.raises(RuntimeError, match="explicit"):
        validate_production_config()
