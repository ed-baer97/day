"""Кто видит заправку и кто меняет учёт.

Имена ролей берутся из level_policy.json, чтобы сервер и кабинет
называли их одинаково.
"""

from __future__ import annotations

from uuid import UUID

from app.domain.policy import ROLE_ADMIN, ROLE_CASHIER, ROLE_OWNER, ROLE_STATION

OWNER_ROLES = frozenset({ROLE_OWNER, ROLE_STATION})
ROLES = frozenset({ROLE_ADMIN, ROLE_STATION, ROLE_OWNER, ROLE_CASHIER})


def is_admin_role(role: str) -> bool:
    return role == ROLE_ADMIN


def is_owner_role(role: str) -> bool:
    return role in OWNER_ROLES


def is_cashier_role(role: str) -> bool:
    return role == ROLE_CASHIER


def may_read_station(role: str, own_station: UUID | None, station_id: UUID) -> bool:
    if is_admin_role(role):
        return True
    return role in (OWNER_ROLES | {ROLE_CASHIER}) and own_station == station_id


def may_manage_catalog(role: str) -> bool:
    """Карточки АГЗС, резервуары, Shelly, газовозы и владельцы."""

    return is_admin_role(role)


def may_manage_cashiers(role: str) -> bool:
    """Создание и привязка кассиров к своим заправкам."""

    return is_owner_role(role)


def may_operate_shift(role: str) -> bool:
    """Открытие и закрытие кассовой смены на заправке."""

    return is_cashier_role(role)


__all__ = [
    "OWNER_ROLES",
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_CASHIER",
    "ROLE_OWNER",
    "ROLE_STATION",
    "is_admin_role",
    "is_cashier_role",
    "is_owner_role",
    "may_manage_cashiers",
    "may_manage_catalog",
    "may_operate_shift",
    "may_read_station",
]
