"""Вход администратора или пользователя станции."""

from uuid import UUID

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SessionOut(BaseModel):
    token: str
    username: str
    role: str = "admin"
    station_id: UUID | None = None
    station_ids: list[UUID] = []


class StationUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class StationUserOut(BaseModel):
    id: UUID
    station_id: UUID
    username: str
    kind: str = "owner"


class StationUserCreated(StationUserOut):
    password: str


class LevelReadingOut(BaseModel):
    id: UUID
    tank_id: UUID
    volts: float | None
    remainder_liters: float
    fill_percent: float | None
    recorded_at: str
    delta_liters: float | None = None
