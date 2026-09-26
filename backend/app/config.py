"""Application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Цифровой след LPG"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    database_url: str = "postgresql+psycopg://lpg:lpg@localhost:5432/lpg_trace"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Balance discrepancy thresholds (liters)
    balance_tolerance_liters: float = 50.0
    measurement_error_band_liters: float = 150.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
