"""Ingest endpoints for AGZS gateway and truck telematics.

Shelly → POST /level (литры или вольты).
Топаз-119-28М → POST /dispense, только чтение, без команд на колонку.
Если задан INGEST_TOKEN, запросы несут заголовок X-Device-Token (или сессию администратора).
"""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth import is_admin_authorization
from app.config import get_settings
from app.schemas.ingest import (
    CalibrationIn,
    DispenseBatchAck,
    DispenseBatchIngest,
    DispenseIngest,
    EdgeFleetSummaryOut,
    EdgeHeartbeatAck,
    EdgeHeartbeatIn,
    EdgeReleaseManifest,
    EdgeReleaseOut,
    GpsIngest,
    IngestAck,
    LevelBatchAck,
    LevelBatchIngest,
    LevelIngest,
    ReceiptIngest,
    TankIngestState,
)
from app.services.account import (
    accept_dispense,
    accept_dispenses_batch,
    accept_level,
    accept_levels_batch,
    accept_receipt,
    bind_calibration,
    bind_dispense,
    bind_level,
    bind_receipt,
    record_truck_position,
    set_calibration,
    tank_by_token,
    tank_state,
)
from app.services.edge_fleet import (
    fleet_summary,
    get_release_for_station,
    publish_release,
    record_heartbeat,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def require_device(
    x_device_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str | None:
    if tank_by_token(x_device_token) is not None:
        return x_device_token
    # Сессия администратора. Флаг тестов сам по себе приём не открывает.
    if authorization and is_admin_authorization(authorization):
        return x_device_token
    expected = get_settings().ingest_token
    if not expected:
        return x_device_token
    if not x_device_token or not hmac.compare_digest(x_device_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="неверный токен устройства")
    return x_device_token


@router.post("/gps", response_model=IngestAck)
def ingest_gps(body: GpsIngest, _: str | None = Depends(require_device)) -> IngestAck:
    return record_truck_position(
        body.truck_id,
        lat=body.lat,
        lon=body.lon,
        recorded_at=body.recorded_at,
        source_event_id=body.source_event_id,
    )


@router.put("/calibration", response_model=TankIngestState)
def calibrate(body: CalibrationIn, token: str | None = Depends(require_device)) -> TankIngestState:
    return set_calibration(bind_calibration(body, token))


@router.post("/level", response_model=IngestAck)
def ingest_level(body: LevelIngest, token: str | None = Depends(require_device)) -> IngestAck:
    return accept_level(bind_level(body, token))


@router.post("/levels/batch", response_model=LevelBatchAck)
def ingest_levels_batch(
    body: LevelBatchIngest, token: str | None = Depends(require_device)
) -> LevelBatchAck:
    """Пакетный приём замеров уровня при восстановлении связи со станцией."""
    bound_items = [bind_level(item, token) for item in body.items]
    return accept_levels_batch(bound_items)


@router.post("/dispense", response_model=IngestAck)
def ingest_dispense(body: DispenseIngest, token: str | None = Depends(require_device)) -> IngestAck:
    """Accept read-only dispense readings from Topaz/ASKA — no control path."""
    return accept_dispense(bind_dispense(body, token))


@router.post("/dispenses/batch", response_model=DispenseBatchAck)
def ingest_dispenses_batch(
    body: DispenseBatchIngest, token: str | None = Depends(require_device)
) -> DispenseBatchAck:
    """Пакетный приём наливов ТРК из очереди outbox edge-компьютера."""
    bound_items = [bind_dispense(item, token) for item in body.items]
    return accept_dispenses_batch(bound_items)


@router.post("/receipt", response_model=IngestAck)
def ingest_receipt(body: ReceiptIngest, token: str | None = Depends(require_device)) -> IngestAck:
    return accept_receipt(bind_receipt(body, token))


@router.get("/tanks/{tank_id}", response_model=TankIngestState)
def ingest_tank(
    tank_id: UUID,
    token: str | None = Depends(require_device),
    authorization: Annotated[str | None, Header()] = None,
) -> TankIngestState:
    device = tank_by_token(token)
    if device is not None and device.tank_id != tank_id:
        raise HTTPException(status_code=403, detail="токен принадлежит другому резервуару")
    settings = get_settings()
    if (
        device is None
        and not settings.ingest_token
        and not is_admin_authorization(authorization)
    ):
        raise HTTPException(status_code=401, detail="Нужен вход или токен резервуара")
    return tank_state(tank_id)


@router.get("/edge/release", response_model=EdgeReleaseOut)
def get_edge_release(
    channel: Annotated[str, Query(pattern="^(stable|canary|ring0|ring1|ring2)$")] = "stable",
    station_code: Annotated[str | None, Query(max_length=64)] = None,
    current_version: Annotated[str | None, Query(max_length=64)] = None,
    outbox_pending: Annotated[int | None, Query(ge=0)] = None,
    _: str | None = Depends(require_device),
) -> EdgeReleaseOut:
    """Возвращает целевой релиз station-edge для АГЗС и при наличии параметров отмечает контакт узла."""
    return get_release_for_station(
        channel=channel,
        station_code=station_code,
        current_version=current_version,
        outbox_pending=outbox_pending,
        record_check=bool(station_code and current_version),
    )


@router.post("/edge/heartbeat", response_model=EdgeHeartbeatAck)
def post_edge_heartbeat(
    body: EdgeHeartbeatIn,
    _: str | None = Depends(require_device),
) -> EdgeHeartbeatAck:
    """Принимает heartbeat со станционного узла (текущая версия, outbox, статус обновления)."""
    return record_heartbeat(body)


@router.put("/edge/release", response_model=EdgeReleaseManifest)
def put_edge_release(
    body: EdgeReleaseManifest,
    canary_stations: Annotated[list[str] | None, Query()] = None,
    ring1_stations: Annotated[list[str] | None, Query()] = None,
    _: str | None = Depends(require_device),
) -> EdgeReleaseManifest:
    """Публикует целевой релиз для кольца (ring0/canary, ring1, ring2/stable) и обновляет списки станций."""
    return publish_release(body, canary_stations=canary_stations, ring1_stations=ring1_stations)


@router.get("/edge/fleet", response_model=EdgeFleetSummaryOut)
def get_edge_fleet(
    _: str | None = Depends(require_device),
) -> EdgeFleetSummaryOut:
    """Возвращает сводку по версиям и состоянию обновлений всех АГЗС."""
    return fleet_summary()
