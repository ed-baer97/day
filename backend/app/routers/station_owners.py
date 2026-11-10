"""Роутер управления учётными записями владельцев АГЗС (/stations/{station_id}/users)."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.schemas.auth import StationUserCreate, StationUserCreated, StationUserOut
from app.services.account_mode import use_postgres
from app.services.catalog import get_station

router = APIRouter(prefix="/stations/{station_id}/users", tags=["station-owners"])


@router.get("", response_model=list[StationUserOut])
def list_station_logins(
    station_id: UUID,
    _admin: str = Depends(require_admin),
) -> list[StationUserOut]:
    get_station(station_id)
    if use_postgres():
        from app.services import postgres_account

        rows = postgres_account.list_station_users(station_id)
    else:
        from app.services.station_accounts import list_owners

        rows = list_owners(station_id)
    return [
        StationUserOut(
            id=row.id,
            station_id=station_id,
            username=row.username,
            kind=getattr(row, "kind", "owner"),
        )
        for row in rows
    ]


@router.post("", response_model=StationUserCreated, status_code=201)
def create_station_login(
    station_id: UUID,
    body: StationUserCreate,
    _admin: str = Depends(require_admin),
) -> StationUserCreated:
    get_station(station_id)
    if use_postgres():
        from app.services import postgres_account

        user = postgres_account.create_station_user(station_id, body.username, body.password)
    else:
        from app.services.station_accounts import grant_owner

        user = grant_owner(station_id, body.username, body.password)
    return StationUserCreated(
        id=user.id,
        station_id=station_id,
        username=user.username,
        kind=getattr(user, "kind", "owner"),
        password=body.password,
    )
