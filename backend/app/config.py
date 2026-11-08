"""Application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__
from app.domain.policy import POLL_SECONDS, SENSOR_STALE_SECONDS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Цифровой след LPG"
    app_version: str = __version__
    api_prefix: str = "/api/v1"
    debug: bool = False

    database_url: str = "postgresql+psycopg://lpg:lpg@localhost:5432/lpg_trace"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # memory — тесты и локальный стенд. postgres — площадка.
    account_store: str = "memory"

    # Файл учёта: заправки, резервуары, токены, шкала, книга остатка.
    # Пусто — только память процесса (локальный запуск и тесты).
    # На площадке с ACCOUNT_STORE=postgres файл читается один раз при пустой базе.
    state_path: str = ""

    # Публичный адрес сайта для карточки резервуара и скрипта Shelly.
    public_base_url: str = "http://localhost:8000"

    # Баланс: пороги расхождений (литры)
    balance_tolerance_liters: float = 50.0
    measurement_error_band_liters: float = 150.0

    # Пусто — приём открыт (стенд). На площадке задайте INGEST_TOKEN.
    ingest_token: str = ""

    # Как часто сервер спрашивает привязанные Shelly по локальной сети.
    # Тот же poll_seconds, что у витрины и скрипта Shelly. Env перекрывает.
    shelly_poll_seconds: float = POLL_SECONDS

    # Нет замера дольше порога — на витрине «нет связи». Env перекрывает.
    sensor_stale_seconds: float = SENSOR_STALE_SECONDS

    # Вход в учёт. На площадке задайте свои ADMIN_USERNAME, ADMIN_PASSWORD и AUTH_SECRET.
    admin_username: str = "admin"
    admin_password: str = "lpg-admin"
    auth_secret: str = "lpg-dev-secret-change-me"
    auth_disabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_postgres(self) -> bool:
        return self.account_store.strip().lower() == "postgres"

    @property
    def ingest_level_path(self) -> str:
        return f"{self.api_prefix.rstrip('/')}/ingest/level"

    @property
    def ingest_level_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.ingest_level_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
