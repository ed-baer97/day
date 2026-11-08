"""Открытый список заполненности. Для сайта, без учёта."""

from fastapi import APIRouter

from app.schemas.public import PublicStationOut
from app.services.public_board import list_public_stations

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/levels", response_model=list[PublicStationOut])
def public_levels() -> list[PublicStationOut]:
    return list_public_stations()
