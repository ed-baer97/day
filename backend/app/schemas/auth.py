"""Вход администратора или пользователя станции."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.access import ROLE_ADMIN
from app.schemas.station import LevelReadingOut

__all__ = [
    "LevelReadingOut",
    "LoginIn",
    "SessionOut",
    "StationUserCreate",
    "StationUserCreated",
    "StationUserOut",
]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SessionOut(BaseModel):
    token: str
    username: str
    role: str = ROLE_ADMIN
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
