"""Реестр релизов station-edge и мониторинг версий парка АГЗС (3 кольца: ring0/canary, ring1, ring2/stable)."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.domain.edge_release import (
    canonical_release_payload,
    derive_ed25519_public_key,
    normalize_channel,
    parse_version_tuple,
    sign_release_ed25519,
    sign_release_manifest,
    verify_release_ed25519,
    verify_release_signature,
)
from app.domain.errors import ValidationError
from app.models.edge import EdgeNodeStatusRecord, EdgeReleaseRecord, EdgeRingStationRecord
from app.models.station import Station
from app.schemas.ingest import (
    EdgeFleetSummaryOut,
    EdgeHeartbeatAck,
    EdgeHeartbeatIn,
    EdgeNodeStatus,
    EdgeReleaseManifest,
    EdgeReleaseOut,
)
from app.services import account_mode
from app.services.memory_state import persist, register_store

_LOCK = threading.RLock()
_RING_ORDER = ("ring0", "ring1", "ring2")
_ZERO_SHA256 = "0" * 64

_RELEASES: dict[str, EdgeReleaseManifest] = {}
_RING0_STATIONS: set[str] = set()
_RING1_STATIONS: set[str] = set()
_NODES: dict[str, EdgeNodeStatus] = {}


@contextmanager
def session() -> Iterator[Session]:
    """Открывает транзакцию SQLAlchemy для PostgreSQL-реестра station-edge."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _prepare_signed_manifest(manifest: EdgeReleaseManifest) -> EdgeReleaseManifest:
    cleaned_sha = manifest.sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", cleaned_sha) or cleaned_sha == _ZERO_SHA256:
        raise ValidationError("укажите реальный SHA-256 артефакта (64 hex-символа, не нули)")

    ring = normalize_channel(manifest.channel)
    settings = get_settings()
    priv_key = settings.edge_release_private_key.strip()
    pub_key = settings.edge_release_public_key.strip()
    hmac_key = settings.edge_release_signing_key.strip()
    sig_in = (manifest.signature or "").strip()

    updates: dict[str, object] = {"channel": ring, "sha256": cleaned_sha}
    if priv_key or pub_key:
        effective_pub = pub_key or derive_ed25519_public_key(priv_key)
        if sig_in:
            if not verify_release_ed25519(
                manifest.version,
                cleaned_sha,
                manifest.min_version,
                sig_in,
                effective_pub,
                channel=ring,
                artifact_url=manifest.artifact_url,
            ):
                raise ValidationError("неверная подпись релиза (Ed25519)")
            updates["signature"] = sig_in.lower()
        elif priv_key:
            updates["signature"] = sign_release_ed25519(
                manifest.version,
                cleaned_sha,
                manifest.min_version,
                priv_key,
                channel=ring,
                artifact_url=manifest.artifact_url,
            )
        else:
            raise ValidationError("укажите подпись Ed25519 или EDGE_RELEASE_PRIVATE_KEY")
    elif hmac_key:
        if sig_in:
            if not verify_release_signature(
                manifest.version,
                cleaned_sha,
                manifest.min_version,
                sig_in,
                hmac_key,
                channel=ring,
                artifact_url=manifest.artifact_url,
            ):
                raise ValidationError("неверная подпись релиза")
            updates["signature"] = sig_in.lower()
        else:
            updates["signature"] = sign_release_manifest(
                manifest.version,
                cleaned_sha,
                manifest.min_version,
                hmac_key,
                channel=ring,
                artifact_url=manifest.artifact_url,
            )
    elif sig_in:
        updates["signature"] = sig_in.lower()

    return manifest.model_copy(update=updates)


def _resolve_target_from_state(
    releases: dict[str, EdgeReleaseManifest],
    ring0_stations: set[str],
    ring1_stations: set[str],
    channel: str,
    station_code: str | None,
) -> tuple[str, EdgeReleaseManifest | None]:
    normalized_code = station_code.strip() if station_code else ""
    if normalized_code and normalized_code in ring0_stations:
        ring = "ring0"
    elif normalized_code and normalized_code in ring1_stations:
        ring = "ring1"
    else:
        ring = normalize_channel(channel)

    if ring == "ring0":
        order = ("ring0", "ring1", "ring2")
    elif ring == "ring1":
        order = ("ring1", "ring2")
    else:
        order = ("ring2",)

    candidates = [releases[item] for item in order if item in releases]
    if not candidates:
        return ring, None
    return ring, max(candidates, key=lambda rel: parse_version_tuple(rel.version))


def _release_out(
    target_ring: str,
    target: EdgeReleaseManifest | None,
    current_version: str | None,
) -> tuple[EdgeReleaseOut, bool]:
    if target is None:
        return (
            EdgeReleaseOut(
                published=False,
                version="",
                artifact_url="",
                sha256="",
                channel=target_ring,
                min_version=None,
                notes="Релиз для кольца ещё не опубликован",
                signature=None,
                update_required=False,
            ),
            False,
        )
    update_required = bool(
        current_version and parse_version_tuple(target.version) > parse_version_tuple(current_version)
    )
    return (
        EdgeReleaseOut(
            published=True,
            version=target.version,
            artifact_url=target.artifact_url,
            sha256=target.sha256,
            channel=target.channel,
            min_version=target.min_version,
            notes=target.notes,
            signature=target.signature,
            update_required=update_required,
        ),
        update_required,
    )


def _replace_ring_stations(
    target_set: set[str],
    other_set: set[str],
    codes: list[str] | None,
) -> None:
    if codes is None:
        return
    target_set.clear()
    for code in codes:
        cleaned = code.strip()
        if cleaned:
            target_set.add(cleaned)
            other_set.discard(cleaned)


def _load_pg_releases_and_rings(
    db: Session,
) -> tuple[dict[str, EdgeReleaseManifest], set[str], set[str]]:
    rel_rows = db.scalars(select(EdgeReleaseRecord)).all()
    releases = {
        row.channel: EdgeReleaseManifest(
            version=row.version,
            artifact_url=row.artifact_url,
            sha256=row.sha256,
            channel=row.channel,
            min_version=row.min_version,
            notes=row.notes or "",
            signature=row.signature,
        )
        for row in rel_rows
    }
    ring_rows = db.scalars(select(EdgeRingStationRecord)).all()
    ring0 = {row.station_code for row in ring_rows if row.ring == "ring0"}
    ring1 = {row.station_code for row in ring_rows if row.ring == "ring1"}
    return releases, ring0, ring1


def _load_pg_nodes(db: Session) -> list[EdgeNodeStatus]:
    rows = db.scalars(select(EdgeNodeStatusRecord).order_by(EdgeNodeStatusRecord.station_code)).all()
    return [
        EdgeNodeStatus(
            station_code=row.station_code,
            station_id=row.station_id,
            current_version=row.current_version,
            target_version=row.target_version,
            channel=row.channel,
            up_to_date=row.up_to_date,
            outbox_pending=row.outbox_pending,
            active_pumps=row.active_pumps,
            update_status=row.update_status,
            last_error=row.last_error,
            last_seen_at=_utc_aware(row.last_seen_at),
        )
        for row in rows
    ]


def _safe_pg_station_id(db: Session, station_id: UUID | None) -> UUID | None:
    if station_id is None:
        return None
    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("stations"):
        return station_id
    return station_id if db.get(Station, station_id) is not None else None


def _upsert_node_pg(
    db: Session,
    *,
    station_code: str,
    station_id: UUID | None,
    current_version: str,
    target_version: str,
    channel: str,
    up_to_date: bool,
    outbox_pending: int,
    active_pumps: int,
    update_status: str,
    last_error: str | None,
) -> None:
    code = station_code.strip()
    if not code:
        return
    now = datetime.now(timezone.utc)
    existing = db.get(EdgeNodeStatusRecord, code)
    resolved_id = _safe_pg_station_id(db, station_id)
    if existing is None:
        db.add(
            EdgeNodeStatusRecord(
                station_code=code,
                station_id=resolved_id,
                current_version=current_version.strip(),
                target_version=target_version,
                channel=channel,
                up_to_date=up_to_date,
                outbox_pending=outbox_pending,
                active_pumps=active_pumps,
                update_status=update_status,
                last_error=last_error,
                last_seen_at=now,
            )
        )
    else:
        existing.station_id = resolved_id if resolved_id is not None else existing.station_id
        existing.current_version = current_version.strip()
        existing.target_version = target_version
        existing.channel = channel
        existing.up_to_date = up_to_date
        existing.outbox_pending = outbox_pending
        existing.active_pumps = active_pumps
        existing.update_status = update_status
        existing.last_error = last_error
        existing.last_seen_at = now


def _upsert_node_memory(
    *,
    station_code: str,
    station_id: UUID | None,
    current_version: str,
    target_version: str,
    channel: str,
    up_to_date: bool,
    outbox_pending: int,
    active_pumps: int,
    update_status: str,
    last_error: str | None,
) -> None:
    code = station_code.strip()
    if not code:
        return
    _NODES[code] = EdgeNodeStatus(
        station_code=code,
        station_id=station_id,
        current_version=current_version.strip(),
        target_version=target_version,
        channel=channel,
        up_to_date=up_to_date,
        outbox_pending=outbox_pending,
        active_pumps=active_pumps,
        update_status=update_status,
        last_error=last_error,
        last_seen_at=datetime.now(timezone.utc),
    )


def get_release_for_station(
    channel: str = "stable",
    station_code: str | None = None,
    current_version: str | None = None,
    *,
    outbox_pending: int | None = None,
    record_check: bool = False,
    station_id: UUID | None = None,
) -> EdgeReleaseOut:
    """Возвращает целевой манифест релиза для конкретной АГЗС (без заглушек)."""
    safe_channel = normalize_channel(channel)
    if account_mode.use_postgres():
        with session() as db:
            releases, ring0, ring1 = _load_pg_releases_and_rings(db)
            target_ring, target = _resolve_target_from_state(
                releases, ring0, ring1, safe_channel, station_code
            )
            out, update_required = _release_out(target_ring, target, current_version)
            if record_check and station_code and current_version:
                code = station_code.strip()
                if code:
                    prev = db.get(EdgeNodeStatusRecord, code)
                    up_to_date = not update_required
                    effective_target = target.version if target is not None else current_version.strip()
                    _upsert_node_pg(
                        db,
                        station_code=code,
                        station_id=station_id if station_id is not None else (prev.station_id if prev else None),
                        current_version=current_version,
                        target_version=effective_target,
                        channel=out.channel,
                        up_to_date=up_to_date,
                        outbox_pending=(
                            outbox_pending
                            if outbox_pending is not None
                            else (prev.outbox_pending if prev else 0)
                        ),
                        active_pumps=prev.active_pumps if prev else 0,
                        update_status=prev.update_status if prev else ("up_to_date" if up_to_date else "checking"),
                        last_error=prev.last_error if prev else None,
                    )
            return out

    should_persist = False
    with _LOCK:
        target_ring, target = _resolve_target_from_state(
            _RELEASES, _RING0_STATIONS, _RING1_STATIONS, safe_channel, station_code
        )
        out, update_required = _release_out(target_ring, target, current_version)
        if record_check and station_code and current_version:
            code = station_code.strip()
            if code:
                prev = _NODES.get(code)
                up_to_date = not update_required
                effective_target = target.version if target is not None else current_version.strip()
                _upsert_node_memory(
                    station_code=code,
                    station_id=station_id if station_id is not None else (prev.station_id if prev else None),
                    current_version=current_version,
                    target_version=effective_target,
                    channel=out.channel,
                    up_to_date=up_to_date,
                    outbox_pending=(
                        outbox_pending
                        if outbox_pending is not None
                        else (prev.outbox_pending if prev else 0)
                    ),
                    active_pumps=prev.active_pumps if prev else 0,
                    update_status=prev.update_status if prev else ("up_to_date" if up_to_date else "checking"),
                    last_error=prev.last_error if prev else None,
                )
                should_persist = True
    if should_persist:
        persist()
    return out


def publish_release(
    manifest: EdgeReleaseManifest,
    *,
    canary_stations: list[str] | None = None,
    ring1_stations: list[str] | None = None,
) -> EdgeReleaseManifest:
    """Публикует новый релиз для кольца (ring0/canary, ring1, ring2/stable) и обновляет списки станций."""
    stored = _prepare_signed_manifest(manifest)
    if account_mode.use_postgres():
        with session() as db:
            row = db.get(EdgeReleaseRecord, stored.channel)
            if row is None:
                db.add(
                    EdgeReleaseRecord(
                        channel=stored.channel,
                        version=stored.version,
                        artifact_url=stored.artifact_url,
                        sha256=stored.sha256,
                        min_version=stored.min_version,
                        notes=stored.notes,
                        signature=stored.signature,
                    )
                )
            else:
                row.version = stored.version
                row.artifact_url = stored.artifact_url
                row.sha256 = stored.sha256
                row.min_version = stored.min_version
                row.notes = stored.notes
                row.signature = stored.signature

            for target_ring, raw_codes in (("ring0", canary_stations), ("ring1", ring1_stations)):
                if raw_codes is None:
                    continue
                db.execute(delete(EdgeRingStationRecord).where(EdgeRingStationRecord.ring == target_ring))
                cleaned_codes = list(dict.fromkeys(c.strip() for c in raw_codes if c and c.strip()))
                for code in cleaned_codes:
                    existing = db.get(EdgeRingStationRecord, code)
                    if existing is None:
                        db.add(EdgeRingStationRecord(station_code=code, ring=target_ring))
                    else:
                        existing.ring = target_ring
        return stored

    with _LOCK:
        _RELEASES[stored.channel] = stored
        _replace_ring_stations(_RING0_STATIONS, _RING1_STATIONS, canary_stations)
        _replace_ring_stations(_RING1_STATIONS, _RING0_STATIONS, ring1_stations)
    persist()
    return stored


def record_heartbeat(hb: EdgeHeartbeatIn) -> EdgeHeartbeatAck:
    """Фиксирует телеметрию узла АГЗС и возвращает целевой релиз."""
    if account_mode.use_postgres():
        with session() as db:
            releases, ring0, ring1 = _load_pg_releases_and_rings(db)
            target_ring, target = _resolve_target_from_state(
                releases, ring0, ring1, normalize_channel(hb.channel), hb.station_code
            )
            release, update_required = _release_out(target_ring, target, hb.current_version)
            up_to_date = not update_required
            target_version = target.version if target is not None else hb.current_version.strip()
            _upsert_node_pg(
                db,
                station_code=hb.station_code,
                station_id=hb.station_id,
                current_version=hb.current_version,
                target_version=target_version,
                channel=release.channel,
                up_to_date=up_to_date,
                outbox_pending=hb.outbox_pending,
                active_pumps=hb.active_pumps,
                update_status=hb.update_status,
                last_error=hb.last_error,
            )
            return EdgeHeartbeatAck(
                accepted=True,
                update_required=update_required,
                release=release,
            )

    with _LOCK:
        release = get_release_for_station(
            channel=hb.channel,
            station_code=hb.station_code,
            current_version=hb.current_version,
        )
        up_to_date = not release.update_required
        target_version = release.version if release.published else hb.current_version.strip()
        _upsert_node_memory(
            station_code=hb.station_code,
            station_id=hb.station_id,
            current_version=hb.current_version,
            target_version=target_version,
            channel=release.channel,
            up_to_date=up_to_date,
            outbox_pending=hb.outbox_pending,
            active_pumps=hb.active_pumps,
            update_status=hb.update_status,
            last_error=hb.last_error,
        )
        ack = EdgeHeartbeatAck(
            accepted=True,
            update_required=not up_to_date,
            release=release,
        )
    persist()
    return ack


def _build_fleet_summary(
    releases: dict[str, EdgeReleaseManifest],
    ring0: set[str],
    ring1: set[str],
    nodes: list[EdgeNodeStatus],
) -> EdgeFleetSummaryOut:
    nodes_out: list[EdgeNodeStatus] = []
    up_to_date_count = 0
    for node in sorted(nodes, key=lambda item: item.station_code):
        target_ring, target = _resolve_target_from_state(
            releases, ring0, ring1, node.channel, node.station_code
        )
        if target is None:
            is_fresh = True
            target_version = node.current_version
            eff_channel = target_ring
        else:
            is_fresh = parse_version_tuple(node.current_version) >= parse_version_tuple(target.version)
            target_version = target.version
            eff_channel = target.channel
        if is_fresh:
            up_to_date_count += 1
        nodes_out.append(
            node.model_copy(
                update={
                    "target_version": target_version,
                    "channel": eff_channel,
                    "up_to_date": is_fresh,
                }
            )
        )
    total = len(nodes_out)
    releases_map: dict[str, EdgeReleaseManifest] = {}
    for ring in _RING_ORDER:
        if ring in releases:
            releases_map[ring] = releases[ring]
    if "ring0" in releases:
        releases_map["canary"] = releases["ring0"]
    if "ring2" in releases:
        releases_map["stable"] = releases["ring2"]
    return EdgeFleetSummaryOut(
        total_nodes=total,
        up_to_date_nodes=up_to_date_count,
        outdated_nodes=total - up_to_date_count,
        releases=releases_map,
        canary_stations=sorted(ring0),
        ring1_stations=sorted(ring1),
        nodes=nodes_out,
    )


def fleet_summary() -> EdgeFleetSummaryOut:
    """Возвращает сводку по всем известным станционным серверам и опубликованным релизам."""
    if account_mode.use_postgres():
        with session() as db:
            releases, ring0, ring1 = _load_pg_releases_and_rings(db)
            nodes = _load_pg_nodes(db)
            return _build_fleet_summary(releases, ring0, ring1, nodes)

    with _LOCK:
        return _build_fleet_summary(
            dict(_RELEASES),
            set(_RING0_STATIONS),
            set(_RING1_STATIONS),
            list(_NODES.values()),
        )


def reset_edge_fleet() -> None:
    """Сбрасывает состояние in-memory реестра релизов и узлов (для тестов)."""
    with _LOCK:
        _RELEASES.clear()
        _RING0_STATIONS.clear()
        _RING1_STATIONS.clear()
        _NODES.clear()


def snapshot() -> dict:
    with _LOCK:
        return {
            "releases": {ring: rel.model_dump(mode="json") for ring, rel in _RELEASES.items()},
            "ring0_stations": sorted(_RING0_STATIONS),
            "ring1_stations": sorted(_RING1_STATIONS),
            "nodes": [node.model_dump(mode="json") for node in _NODES.values()],
        }


def restore_snapshot(data: dict) -> None:
    if not isinstance(data, dict):
        return
    with _LOCK:
        releases = data.get("releases")
        if isinstance(releases, dict):
            restored_releases: dict[str, EdgeReleaseManifest] = {}
            for ring in _RING_ORDER:
                raw_rel = releases.get(ring)
                if isinstance(raw_rel, dict):
                    rel = EdgeReleaseManifest.model_validate(raw_rel)
                    if rel.sha256.strip().lower() != _ZERO_SHA256:
                        restored_releases[ring] = rel
            _RELEASES.clear()
            _RELEASES.update(restored_releases)
        if "ring0_stations" in data and isinstance(data["ring0_stations"], list):
            _RING0_STATIONS.clear()
            _RING1_STATIONS.clear()
            _replace_ring_stations(
                _RING0_STATIONS, _RING1_STATIONS, [str(x) for x in data["ring0_stations"]]
            )
        if "ring1_stations" in data and isinstance(data["ring1_stations"], list):
            _replace_ring_stations(
                _RING1_STATIONS, _RING0_STATIONS, [str(x) for x in data["ring1_stations"]]
            )
        if "nodes" in data and isinstance(data["nodes"], list):
            _NODES.clear()
            for raw_node in data["nodes"]:
                node = EdgeNodeStatus.model_validate(raw_node)
                _NODES[node.station_code] = node


register_store("edge_fleet", snapshot, restore_snapshot)

__all__ = [
    "canonical_release_payload",
    "fleet_summary",
    "get_release_for_station",
    "normalize_channel",
    "parse_version_tuple",
    "publish_release",
    "record_heartbeat",
    "reset_edge_fleet",
    "restore_snapshot",
    "session",
    "sign_release_ed25519",
    "sign_release_manifest",
    "snapshot",
    "verify_release_ed25519",
    "verify_release_signature",
]
