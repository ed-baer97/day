"""Ingest endpoints for AGZS gateway and truck telematics.

Shelly / edge → POST /level, /dispense, /dispenses/batch (токен резервуара или админ).
Калибровка и приёмка → только администратор.
GPS газовозов → отдельный GPS_INGEST_TOKEN / INGEST_TOKEN или администратор.
"""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.auth import has_valid_admin_token, require_admin
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
from app.services.ingest_auth import (
    IngestCaller,
    assert_tank_read_access,
    bind_dispense_for_caller,
    bind_level_for_caller,
    resolve_edge_station_scope,
    resolve_tank_device_caller,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _token_matches(provided: str | None, expected: str) -> bool:
    return bool(provided and expected and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")))


def require_tank_telemetry_caller(
    x_device_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> IngestCaller:
    """Проверяет токен резервуара, общий INGEST_TOKEN или реальный Bearer-токен администратора."""
    if x_device_token:
        tank_caller = resolve_tank_device_caller(x_device_token)
        if tank_caller is not None:
            return tank_caller
    settings = get_settings()
    if _token_matches(x_device_token, settings.ingest_token):
        return IngestCaller(kind="shared_ingest")
    if has_valid_admin_token(authorization):
        return IngestCaller(kind="admin")
    if (
        settings.allow_anonymous_ingest
        and not settings.ingest_token
        and not x_device_token
        and not authorization
    ):
        return IngestCaller(kind="anonymous")
    raise HTTPException(status_code=401, detail="неверный токен устройства")


def require_gps_caller(
    x_device_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> IngestCaller:
    """Проверяет отдельный GPS-токен, INGEST_TOKEN или токен админа; токен резервуара отклоняется."""
    if x_device_token and tank_by_token(x_device_token) is not None:
        raise HTTPException(
            status_code=403,
            detail="токен резервуара АГЗС не допускается для GPS газовозов",
        )
    settings = get_settings()
    expected_gps = settings.gps_ingest_token or settings.ingest_token
    if _token_matches(x_device_token, expected_gps):
        return IngestCaller(kind="gps_device")
    if has_valid_admin_token(authorization):
        return IngestCaller(kind="admin")
    if (
        settings.allow_anonymous_ingest
        and not expected_gps
        and not x_device_token
        and not authorization
    ):
        return IngestCaller(kind="anonymous")
    raise HTTPException(status_code=401, detail="неверный токен GPS")


@router.post("/gps", response_model=IngestAck)
def ingest_gps(body: GpsIngest, _: IngestCaller = Depends(require_gps_caller)) -> IngestAck:
    return record_truck_position(
        body.truck_id,
        lat=body.lat,
        lon=body.lon,
        recorded_at=body.recorded_at,
        source_event_id=body.source_event_id,
    )


@router.put("/calibration", response_model=TankIngestState)
def calibrate(body: CalibrationIn, _: str = Depends(require_admin)) -> TankIngestState:
    return set_calibration(bind_calibration(body))


@router.post("/level", response_model=IngestAck)
def ingest_level(
    body: LevelIngest, caller: IngestCaller = Depends(require_tank_telemetry_caller)
) -> IngestAck:
    return accept_level(bind_level_for_caller(body, caller))


@router.post("/levels/batch", response_model=LevelBatchAck)
def ingest_levels_batch(
    body: LevelBatchIngest, caller: IngestCaller = Depends(require_tank_telemetry_caller)
) -> LevelBatchAck:
    """Пакетный приём замеров уровня при восстановлении связи со станцией."""
    bound_items = [bind_level_for_caller(item, caller) for item in body.items]
    return accept_levels_batch(bound_items)


@router.post("/dispense", response_model=IngestAck)
def ingest_dispense(
    body: DispenseIngest, caller: IngestCaller = Depends(require_tank_telemetry_caller)
) -> IngestAck:
    """Accept read-only dispense readings from Topaz/ASKA — no control path."""
    return accept_dispense(bind_dispense_for_caller(body, caller))


@router.post("/dispenses/batch", response_model=DispenseBatchAck)
def ingest_dispenses_batch(
    body: DispenseBatchIngest, caller: IngestCaller = Depends(require_tank_telemetry_caller)
) -> DispenseBatchAck:
    """Пакетный приём наливов ТРК из очереди outbox edge-компьютера."""
    bound_items = [bind_dispense_for_caller(item, caller) for item in body.items]
    return accept_dispenses_batch(bound_items)


@router.post("/receipt", response_model=IngestAck)
def ingest_receipt(body: ReceiptIngest, _: str = Depends(require_admin)) -> IngestAck:
    return accept_receipt(body)


@router.get("/tanks/{tank_id}", response_model=TankIngestState)
def ingest_tank(
    tank_id: UUID,
    caller: IngestCaller = Depends(require_tank_telemetry_caller),
) -> TankIngestState:
    assert_tank_read_access(tank_id, caller)
    return tank_state(tank_id)


@router.get("/edge/release", response_model=EdgeReleaseOut)
def get_edge_release(
    channel: Annotated[str, Query(pattern="^(stable|canary|ring0|ring1|ring2)$")] = "stable",
    station_code: Annotated[str | None, Query(max_length=64)] = None,
    current_version: Annotated[str | None, Query(max_length=64)] = None,
    outbox_pending: Annotated[int | None, Query(ge=0)] = None,
    caller: IngestCaller = Depends(require_tank_telemetry_caller),
) -> EdgeReleaseOut:
    """Возвращает целевой релиз station-edge для АГЗС, привязывая код к токену станции."""
    eff_code, eff_station_id = resolve_edge_station_scope(caller, station_code)
    return get_release_for_station(
        channel=channel,
        station_code=eff_code,
        current_version=current_version,
        outbox_pending=outbox_pending,
        record_check=bool(eff_code and current_version),
        station_id=eff_station_id,
    )


@router.post("/edge/heartbeat", response_model=EdgeHeartbeatAck)
def post_edge_heartbeat(
    body: EdgeHeartbeatIn,
    caller: IngestCaller = Depends(require_tank_telemetry_caller),
) -> EdgeHeartbeatAck:
    """Принимает heartbeat со станционного узла (код АГЗС и station_id проверяются по токену)."""
    eff_code, eff_station_id = resolve_edge_station_scope(caller, body.station_code, body.station_id)
    bound_body = body.model_copy(
        update={
            "station_code": eff_code or body.station_code,
            "station_id": eff_station_id,
        }
    )
    return record_heartbeat(bound_body)


@router.put("/edge/release", response_model=EdgeReleaseManifest)
def put_edge_release(
    body: EdgeReleaseManifest,
    canary_stations: Annotated[list[str] | None, Query()] = None,
    ring1_stations: Annotated[list[str] | None, Query()] = None,
    _: str = Depends(require_admin),
) -> EdgeReleaseManifest:
    """Публикует целевой релиз для кольца (ring0/canary, ring1, ring2/stable) и обновляет списки станций."""
    return publish_release(body, canary_stations=canary_stations, ring1_stations=ring1_stations)


@router.get("/edge/fleet", response_model=EdgeFleetSummaryOut)
def get_edge_fleet(
    _: str = Depends(require_admin),
) -> EdgeFleetSummaryOut:
    """Возвращает сводку по версиям и состоянию обновлений всех АГЗС."""
    return fleet_summary()
