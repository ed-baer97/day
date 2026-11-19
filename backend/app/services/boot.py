"""Старт площадки: миграции и разовый перенос state.json в Postgres."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    settings = get_settings()
    if not settings.use_postgres:
        return
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    logger.info("миграции применены")


def restore_memory_state() -> None:
    """Регистрирует все in-memory хранилища и восстанавливает state.json при режиме memory."""
    settings = get_settings()
    if settings.use_postgres:
        return
    import app.services.batch_book  # noqa: F401
    import app.services.memory_account  # noqa: F401
    import app.services.shelly_link  # noqa: F401
    from app.services.memory_state import restore

    restore()


def _read_state_snapshot(state_path: str) -> dict | None:
    path = state_path.strip()
    file_path = Path(path) if path else None
    if file_path is None or not file_path.is_file():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("state.json не прочитан")
        return None
    return data if isinstance(data, dict) else None


def import_state_if_empty() -> None:
    settings = get_settings()
    if not settings.use_postgres:
        return
    from uuid import UUID

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.batch import Batch
    from app.models.station import Station
    from app.services import postgres_account

    with SessionLocal() as db:
        has_stations = db.scalar(select(Station.id).limit(1)) is not None
        has_batches = db.scalar(select(Batch.id).limit(1)) is not None

    if has_stations and has_batches:
        return

    data = _read_state_snapshot(settings.state_path)
    if has_stations:
        raw_batches = data.get("batches") if isinstance(data, dict) else None
        if isinstance(raw_batches, list) and raw_batches:
            imported = postgres_account.import_batches_snapshot(raw_batches)
            if imported > 0:
                logger.info("перенесены партии из state.json в Postgres: %d", imported)
        return

    if data is not None:
        postgres_account.import_memory_snapshot(data)
        return

    with SessionLocal() as db:
        db.add(
            Station(
                id=UUID("a1111111-1111-1111-1111-111111111101"),
                code="AGZS-AKT-12",
                name="АГЗС Актау · 12 мкр",
                address="Актау, 12 микрорайон",
                lat=43.6479,
                lon=51.2480,
                is_active=True,
                columns_mode="virtual",
                columns_count=2,
            )
        )
        db.commit()
    logger.info("создана стартовая АГЗС Актау · 12 мкр")
