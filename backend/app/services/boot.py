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
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    logger.info("миграции применены")


def import_state_if_empty() -> None:
    settings = get_settings()
    if not settings.use_postgres:
        return
    from uuid import UUID

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.station import Station
    from app.services import postgres_account

    with SessionLocal() as db:
        if db.scalar(select(Station).limit(1)) is not None:
            return

    path = settings.state_path.strip()
    file_path = Path(path) if path else None
    if file_path is not None and file_path.is_file():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("state.json не прочитан")
            data = None
        if isinstance(data, dict):
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
            )
        )
        db.commit()
    logger.info("создана стартовая АГЗС Актау · 12 мкр")
