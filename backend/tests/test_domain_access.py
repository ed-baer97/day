"""Прямые доменные тесты матрицы доступа (app.domain.access)."""

from __future__ import annotations

from uuid import uuid4

from app.domain.access import (
    ROLE_ADMIN,
    ROLE_CASHIER,
    ROLE_OWNER,
    ROLE_STATION,
    may_list_cashiers,
    may_manage_cashiers,
    may_manage_catalog,
    may_operate_shift,
    may_read_station,
    may_read_station_cashiers,
)


def test_owner_with_two_stations_access():
    s1, s2, s3 = uuid4(), uuid4(), uuid4()
    own = (s1, s2)

    for role in (ROLE_OWNER, ROLE_STATION):
        assert may_read_station(role, own, s1) is True
        assert may_read_station(role, own, s2) is True
        assert may_read_station(role, own, s3) is False

        assert may_list_cashiers(role) is True
        assert may_read_station_cashiers(role, own, s1) is True
        assert may_read_station_cashiers(role, own, s2) is True
        assert may_read_station_cashiers(role, own, s3) is False

        assert may_manage_cashiers(role, own, s1) is True
        assert may_manage_cashiers(role, own, s2) is True
        assert may_manage_cashiers(role, own, s3) is False

        assert may_operate_shift(role, own, s1) is False
        assert may_manage_catalog(role) is False


def test_cashier_reads_and_operates_only_own_station():
    s1, s2 = uuid4(), uuid4()
    own = (s1,)

    assert may_read_station(ROLE_CASHIER, own, s1) is True
    assert may_read_station(ROLE_CASHIER, own, s2) is False

    assert may_operate_shift(ROLE_CASHIER, own, s1) is True
    assert may_operate_shift(ROLE_CASHIER, own, s2) is False

    assert may_list_cashiers(ROLE_CASHIER) is False
    assert may_read_station_cashiers(ROLE_CASHIER, own, s1) is False
    assert may_manage_cashiers(ROLE_CASHIER, own, s1) is False
    assert may_manage_catalog(ROLE_CASHIER) is False


def test_admin_reads_all_and_cannot_operate_shifts_or_manage_station_cashiers():
    s1, s2 = uuid4(), uuid4()

    assert may_read_station(ROLE_ADMIN, (), s1) is True
    assert may_read_station(ROLE_ADMIN, (), s2) is True
    assert may_manage_catalog(ROLE_ADMIN) is True
    assert may_list_cashiers(ROLE_ADMIN) is True
    assert may_read_station_cashiers(ROLE_ADMIN, (), s1) is True

    assert may_manage_cashiers(ROLE_ADMIN, (), s1) is False
    assert may_manage_cashiers(ROLE_ADMIN, (s1,), s1) is False
    assert may_operate_shift(ROLE_ADMIN, (), s1) is False
    assert may_operate_shift(ROLE_ADMIN, (s1,), s1) is False


def test_unknown_or_empty_role_has_no_access():
    s1 = uuid4()

    for role in ("guest", "", "superuser"):
        assert may_read_station(role, (s1,), s1) is False
        assert may_manage_catalog(role) is False
        assert may_list_cashiers(role) is False
        assert may_read_station_cashiers(role, (s1,), s1) is False
        assert may_manage_cashiers(role, (s1,), s1) is False
        assert may_operate_shift(role, (s1,), s1) is False
