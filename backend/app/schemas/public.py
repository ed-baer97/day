"""Публичная заполненность резервуаров. Без ключей и без сверки."""

from datetime import datetime

from pydantic import BaseModel


class PublicTankOut(BaseModel):
    code: str
    capacity_liters: float
    remainder_liters: float | None
    fill_percent: float | None
    measured_at: datetime | None


class PublicStationOut(BaseModel):
    code: str
    name: str
    address: str | None
    tanks: list[PublicTankOut]
