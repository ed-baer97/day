"""Кто видит заправку и кто меняет учёт.

Имена ролей берутся из level_policy.json, чтобы сервер и кабинет
называли их одинаково.
"""

from __future__ import annotations

from uuid import UUID

from app.domain.policy import ROLE_ADMIN, ROLE_STATION

ROLES = frozenset({ROLE_ADMIN, ROLE_STATION})


def is_admin_role(role: str) -> bool:
    return role == ROLE_ADMIN


def may_read_station(role: str, own_station: UUID | None, station_id: UUID) -> bool:
    if is_admin_role(role):
        return True
    return role == ROLE_STATION and own_station == station_id


def may_manage_catalog(role: str) -> bool:
    """Карточки АГЗС, резервуары, Shelly, газовозы и пользователи станции."""

    return is_admin_role(role)
