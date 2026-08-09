import os
import base64
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ValuSee"
    app_env: str = "dev"
    max_scan_files: int = 800
    max_file_preview_chars: int = 4000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


def validate_production_config() -> None:
    if os.getenv("APP_ENV", settings.app_env).lower() not in {"prod", "production"}:
        return
    required_secrets = {
        "VALUSee_JWT_SECRET": 32,
        "VALUSee_METRICS_TOKEN": 24,
        "VALUSee_MFA_ENCRYPTION_KEY": 43,
    }
    for name, minimum in required_secrets.items():
        value = os.getenv(name, "").strip()
        if len(value) < minimum or "replace-with" in value.lower() or "change-this" in value.lower():
            raise RuntimeError(f"production requires a strong {name} ({minimum}+ characters)")
        if name == "VALUSee_MFA_ENCRYPTION_KEY":
            try:
                if len(base64.urlsafe_b64decode(value.encode("ascii"))) != 32:
                    raise ValueError
            except (ValueError, UnicodeError) as exc:
                raise RuntimeError("VALUSee_MFA_ENCRYPTION_KEY must be a generated Fernet key") from exc
    if not os.getenv("VALUSee_ADMIN_EMAILS", "").strip():
        raise RuntimeError("production requires VALUSee_ADMIN_EMAILS")
    hosts = {item.strip() for item in os.getenv("ALLOWED_HOSTS", "").split(",") if item.strip()}
    origins = {item.strip() for item in os.getenv("ALLOWED_ORIGINS", "").split(",") if item.strip()}
    if not hosts or "*" in hosts or not origins or "*" in origins:
        raise RuntimeError("production requires explicit ALLOWED_HOSTS and ALLOWED_ORIGINS")
    if any(urlparse(origin).scheme != "https" for origin in origins):
        raise RuntimeError("production origins must use HTTPS")
    public_url = os.getenv("VALUSee_PUBLIC_BASE_URL", "").strip()
    if urlparse(public_url).scheme != "https" or not urlparse(public_url).hostname:
        raise RuntimeError("production requires an HTTPS VALUSee_PUBLIC_BASE_URL")
