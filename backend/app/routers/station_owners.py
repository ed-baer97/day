"""Роутер управления учётными записями владельцев АГЗС (/stations/{station_id}/users)."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.schemas.auth import StationUserCreate, StationUserCreated, StationUserOut
from app.services.account import create_station_user, get_station, list_station_users

router = APIRouter(prefix="/stations/{station_id}/users", tags=["station-owners"])


@router.get("", response_model=list[StationUserOut])
def list_station_logins(
    station_id: UUID,
    _admin: str = Depends(require_admin),
) -> list[StationUserOut]:
    get_station(station_id)
    rows = list_station_users(station_id)
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
    user = create_station_user(station_id, body.username, body.password)
    return StationUserCreated(
        id=user.id,
        station_id=station_id,
        username=user.username,
        kind=getattr(user, "kind", "owner"),
        password=body.password,
    )
