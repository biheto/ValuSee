from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DevAgent Studio"
    app_env: str = "dev"
    max_scan_files: int = 800
    max_file_preview_chars: int = 4000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
