"""Роутер управления учётными записями кассиров АГЗС."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import (
    Principal,
    require_principal,
    require_station_manager_or_admin,
    require_station_owner,
)
from app.schemas.auth import CashierCreate, CashierCreated, CashierOut, CashierUpdate
from app.services.account import (
    create_station_cashier,
    delete_station_cashier,
    get_station,
    list_cashiers_for_stations,
    list_station_cashiers,
    update_station_cashier,
)

router = APIRouter(tags=["cashiers"])


def _to_out(cashier) -> CashierOut:
    return CashierOut(
        id=cashier.id,
        station_id=cashier.station_id,
        username=cashier.username,
        kind=getattr(cashier, "kind", "cashier"),
    )


@router.get("/cashiers", response_model=list[CashierOut])
def list_visible_cashiers(
    principal: Principal = Depends(require_principal),
) -> list[CashierOut]:
    if principal.is_admin:
        rows = list_cashiers_for_stations(None)
    elif principal.is_owner:
        rows = list_cashiers_for_stations(list(principal.stations()))
    else:
        raise HTTPException(status_code=403, detail="доступ только для владельца или администратора")
    return [_to_out(row) for row in rows]


@router.get("/stations/{station_id}/cashiers", response_model=list[CashierOut])
def list_station_cashier_accounts(
    station_id: UUID,
    principal: Principal = Depends(require_principal),
) -> list[CashierOut]:
    require_station_manager_or_admin(station_id, principal)
    get_station(station_id)
    return [_to_out(row) for row in list_station_cashiers(station_id)]


@router.post("/stations/{station_id}/cashiers", response_model=CashierCreated, status_code=201)
def create_station_cashier_account(
    station_id: UUID,
    body: CashierCreate,
    principal: Principal = Depends(require_principal),
) -> CashierCreated:
    require_station_owner(station_id, principal)
    get_station(station_id)
    cashier = create_station_cashier(station_id, body.username, body.password)
    return CashierCreated(**_to_out(cashier).model_dump(), password=body.password)


@router.patch("/stations/{station_id}/cashiers/{username}", response_model=CashierOut)
def patch_station_cashier_account(
    station_id: UUID,
    username: str,
    body: CashierUpdate,
    principal: Principal = Depends(require_principal),
) -> CashierOut:
    require_station_owner(station_id, principal)
    get_station(station_id)
    if body.station_id is not None:
        require_station_owner(body.station_id, principal)
        get_station(body.station_id)
    fields = body.model_fields_set
    updated = update_station_cashier(
        station_id,
        username,
        password=body.password if "password" in fields else None,
        new_station_id=body.station_id if "station_id" in fields else None,
    )
    return _to_out(updated)


@router.delete("/stations/{station_id}/cashiers/{username}", status_code=204)
def remove_station_cashier_account(
    station_id: UUID,
    username: str,
    principal: Principal = Depends(require_principal),
) -> Response:
    require_station_owner(station_id, principal)
    get_station(station_id)
    delete_station_cashier(station_id, username)
    return Response(status_code=204)
