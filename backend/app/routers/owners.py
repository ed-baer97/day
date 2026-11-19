"""Роутер единого управления владельцами АГЗС (/api/v1/owners)."""

from fastapi import APIRouter, Depends, Response

from app.auth import require_admin
from app.schemas.auth import (
    OwnerAccountCreate,
    OwnerAccountCreated,
    OwnerAccountOut,
    OwnerAccountUpdate,
)
from app.services.account import (
    create_owner_account,
    delete_owner_account,
    list_all_owners,
    update_owner_account,
)

router = APIRouter(prefix="/owners", tags=["owners"])


def _to_out(owner) -> OwnerAccountOut:
    return OwnerAccountOut(
        id=owner.id,
        username=owner.username,
        kind=getattr(owner, "kind", "owner"),
        station_ids=owner.stations(),
    )


@router.get("", response_model=list[OwnerAccountOut])
def list_owners(_admin: str = Depends(require_admin)) -> list[OwnerAccountOut]:
    return [_to_out(owner) for owner in list_all_owners()]


@router.post("", response_model=OwnerAccountCreated, status_code=201)
def create_owner(
    body: OwnerAccountCreate,
    _admin: str = Depends(require_admin),
) -> OwnerAccountCreated:
    owner = create_owner_account(body.username, body.password, body.station_ids)
    return OwnerAccountCreated(
        **_to_out(owner).model_dump(),
        password=body.password,
    )


@router.patch("/{username}", response_model=OwnerAccountOut)
def patch_owner(
    username: str,
    body: OwnerAccountUpdate,
    _admin: str = Depends(require_admin),
) -> OwnerAccountOut:
    fields = body.model_fields_set
    owner = update_owner_account(
        username,
        station_ids=body.station_ids if "station_ids" in fields else None,
        password=body.password if "password" in fields else None,
    )
    return _to_out(owner)


@router.delete("/{username}", status_code=204)
def remove_owner(username: str, _admin: str = Depends(require_admin)) -> Response:
    delete_owner_account(username)
    return Response(status_code=204)
