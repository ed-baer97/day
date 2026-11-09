"""Пульт колонок. Команды остаются внутри API и не уходят на оборудование."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import Principal, require_principal, require_station_access, require_station_owner
from app.schemas.auth import StationUserCreate, StationUserCreated, StationUserOut
from app.schemas.console import (
    ConsoleAction,
    ConsoleFace,
    CabinetFace,
    DoseIn,
    IncidentRow,
    JournalRow,
    LatchIn,
    LinkIn,
    PriceIn,
)
from app.services.pump_console import (
    console_acknowledge,
    console_cabinet,
    console_close_shift,
    console_incidents,
    console_journal,
    console_latch,
    console_link,
    console_open_shift,
    console_set_price,
    console_snapshot,
    console_start,
    console_stop,
    console_tick,
)

router = APIRouter(prefix="/stations/{station_id}/console", tags=["console"])


def _guard(station_id: UUID, principal: Principal = Depends(require_principal)) -> None:
    require_station_access(station_id, principal)


@router.get("", response_model=ConsoleFace)
def read_console(station_id: UUID, _: None = Depends(_guard)) -> dict:
    return console_snapshot(station_id)


@router.post("/tick", response_model=ConsoleFace)
def tick_console(station_id: UUID, _: None = Depends(_guard)) -> dict:
    return console_tick(station_id)


@router.post("/shift/open", response_model=ConsoleFace)
def open_shift(station_id: UUID, _: None = Depends(_guard)) -> dict:
    return console_open_shift(station_id)


@router.post("/shift/close", response_model=ConsoleAction)
def close_shift(station_id: UUID, _: None = Depends(_guard)) -> dict:
    message, desk = console_close_shift(station_id)
    return {"message": message, "desk": desk}


@router.post("/pumps/{pump_id}/start", response_model=ConsoleAction)
def start_pump(station_id: UUID, pump_id: UUID, body: DoseIn, _: None = Depends(_guard)) -> dict:
    message, desk = console_start(station_id, pump_id, body.mode, body.buffer)
    return {"message": message, "desk": desk}


@router.post("/pumps/{pump_id}/stop", response_model=ConsoleAction)
def stop_pump(station_id: UUID, pump_id: UUID, _: None = Depends(_guard)) -> dict:
    message, desk = console_stop(station_id, pump_id)
    return {"message": message, "desk": desk}


@router.post("/commands", response_model=ConsoleAction)
def latch_commands(station_id: UUID, body: LatchIn, _: None = Depends(_guard)) -> dict:
    message, desk = console_latch(station_id, body.latched)
    return {"message": message, "desk": desk}


@router.post("/link", response_model=ConsoleAction)
def set_link(station_id: UUID, body: LinkIn, _: None = Depends(_guard)) -> dict:
    message, desk = console_link(station_id, body.up)
    return {"message": message, "desk": desk}


@router.get("/cabinet", response_model=CabinetFace)
def read_cabinet(station_id: UUID, _: None = Depends(_guard)) -> dict:
    return console_cabinet(station_id)


@router.put("/cabinet/price", response_model=CabinetFace)
def write_price(station_id: UUID, body: PriceIn, principal: Principal = Depends(require_principal)) -> dict:
    require_station_access(station_id, principal)
    if principal.role not in ("owner", "station"):
        raise HTTPException(status_code=403, detail="цену газа задаёт владелец заправки")
    return console_set_price(station_id, body.price_kzt_per_liter)


@router.get("/admins", response_model=list[StationUserOut])
def list_console_admins(station_id: UUID, principal: Principal = Depends(require_principal)) -> list[StationUserOut]:
    require_station_access(station_id, principal)
    from app.services.account_mode import use_postgres
    from app.services.station_accounts import list_console_admins as list_memory

    if use_postgres():
        return []
    return [
        StationUserOut(id=row.id, station_id=station_id, username=row.username, kind="console")
        for row in list_memory(station_id)
    ]


@router.post("/admins", response_model=StationUserCreated, status_code=201)
def create_console_admin(
    station_id: UUID,
    body: StationUserCreate,
    principal: Principal = Depends(require_principal),
) -> StationUserCreated:
    require_station_owner(station_id, principal)
    from app.services.account_mode import use_postgres
    from app.services.catalog import get_station
    from app.services.station_accounts import create_console_admin as create_memory

    get_station(station_id)
    if use_postgres():
        raise HTTPException(status_code=501, detail="администраторы пульта в этой базе ещё не заведены")
    if len(body.password) < 6:
        raise HTTPException(status_code=422, detail="пароль администратора пульта не короче 6 символов")
    user = create_memory(station_id, body.username, body.password)
    return StationUserCreated(
        id=user.id,
        station_id=station_id,
        username=user.username,
        kind="console",
        password=body.password,
    )


@router.get("/journal", response_model=list[JournalRow])
def read_journal(station_id: UUID, _: None = Depends(_guard)) -> list[dict]:
    return console_journal(station_id)


@router.get("/incidents", response_model=list[IncidentRow])
def read_incidents(station_id: UUID, _: None = Depends(_guard)) -> list[dict]:
    return console_incidents(station_id)


@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentRow)
def acknowledge_incident(station_id: UUID, incident_id: UUID, _: None = Depends(_guard)) -> dict:
    return console_acknowledge(station_id, incident_id)
