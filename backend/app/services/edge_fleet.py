"""Реестр релизов station-edge и мониторинг версий парка АГЗС (3 кольца: ring0/canary, ring1, ring2/stable)."""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from datetime import datetime, timezone

from app.config import get_settings
from app.domain.errors import ValidationError
from app.schemas.ingest import (
    EdgeFleetSummaryOut,
    EdgeHeartbeatAck,
    EdgeHeartbeatIn,
    EdgeNodeStatus,
    EdgeReleaseManifest,
    EdgeReleaseOut,
)

_LOCK = threading.RLock()

_RING_ORDER = ("ring0", "ring1", "ring2")


def canonical_release_payload(version: str, sha256: str, min_version: str | None) -> bytes:
    """Каноническая строка для HMAC-SHA256 подписи OTA-манифеста station-edge."""
    return f"{version.strip()}\n{sha256.strip().lower()}\n{(min_version or '').strip()}".encode("utf-8")


def sign_release_manifest(
    version: str,
    sha256: str,
    min_version: str | None,
    signing_key: str,
) -> str:
    """Вычисляет HMAC-SHA256 (hex lowercase) для релиза station-edge."""
    return hmac.new(
        signing_key.strip().encode("utf-8"),
        canonical_release_payload(version, sha256, min_version),
        hashlib.sha256,
    ).hexdigest().lower()


def verify_release_signature(manifest: EdgeReleaseManifest, signing_key: str) -> bool:
    """Проверяет криптографическую подпись манифеста HMAC-SHA256."""
    sig = (manifest.signature or "").strip().lower()
    key = signing_key.strip()
    if not sig or not key:
        return False
    expected = sign_release_manifest(
        manifest.version,
        manifest.sha256,
        manifest.min_version,
        key,
    )
    return hmac.compare_digest(sig, expected)


def normalize_channel(channel: str) -> str:
    """Нормализует имя канала в одно из трёх колец: ring0, ring1 или ring2."""
    token = (channel or "").strip().lower()
    if token in {"canary", "ring0"}:
        return "ring0"
    if token == "ring1":
        return "ring1"
    return "ring2"


def _default_releases() -> dict[str, EdgeReleaseManifest]:
    return {
        "ring0": EdgeReleaseManifest(
            version="0.1.0",
            artifact_url="/releases/agzs_edge-0.1.0-py3-none-any.whl",
            sha256="0" * 64,
            channel="ring0",
            notes="Кольцо 0 (1–2 тестовые станции рядом с инженером, обкатка сутки)",
        ),
        "ring1": EdgeReleaseManifest(
            version="0.1.0",
            artifact_url="/releases/agzs_edge-0.1.0-py3-none-any.whl",
            sha256="0" * 64,
            channel="ring1",
            notes="Кольцо 1 (10% станций, обкатка 1 смену)",
        ),
        "ring2": EdgeReleaseManifest(
            version="0.1.0",
            artifact_url="/releases/agzs_edge-0.1.0-py3-none-any.whl",
            sha256="0" * 64,
            channel="ring2",
            notes="Кольцо 2 (остальные 90% станций, обновление во время простоя)",
        ),
    }


_RELEASES: dict[str, EdgeReleaseManifest] = _default_releases()
_RING0_STATIONS: set[str] = set()
_RING1_STATIONS: set[str] = set()


_NODES: dict[str, EdgeNodeStatus] = {}


def parse_version_tuple(version: str) -> tuple[int, ...]:
    """Разбирает строку версии ('0.2.1', 'v1.0.3') в кортеж целых чисел."""
    cleaned = version.strip().lstrip("vV")
    if not cleaned:
        return (0,)
    parts: list[int] = []
    for token in cleaned.split("."):
        match = re.match(r"^(\d+)", token.strip())
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def _resolve_target_manifest(channel: str, station_code: str | None) -> EdgeReleaseManifest:
    normalized_code = station_code.strip() if station_code else ""
    if normalized_code and normalized_code in _RING0_STATIONS:
        ring = "ring0"
    elif normalized_code and normalized_code in _RING1_STATIONS:
        ring = "ring1"
    else:
        ring = normalize_channel(channel)

    if ring == "ring0":
        candidates = [_RELEASES["ring0"], _RELEASES["ring1"], _RELEASES["ring2"]]
    elif ring == "ring1":
        candidates = [_RELEASES["ring1"], _RELEASES["ring2"]]
    else:
        candidates = [_RELEASES["ring2"]]

    return max(candidates, key=lambda rel: parse_version_tuple(rel.version))


def _upsert_node_status(
    *,
    station_code: str,
    station_id,
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


def _replace_ring_stations(target_set: set[str], codes: list[str] | None) -> None:
    if codes is None:
        return
    target_set.clear()
    for code in codes:
        cleaned = code.strip()
        if cleaned:
            target_set.add(cleaned)


def get_release_for_station(
    channel: str = "stable",
    station_code: str | None = None,
    current_version: str | None = None,
    *,
    outbox_pending: int | None = None,
    record_check: bool = False,
) -> EdgeReleaseOut:
    """Возвращает целевой манифест релиза для конкретной АГЗС (учитывая кольца ring0/ring1/ring2)."""
    safe_channel = normalize_channel(channel)
    with _LOCK:
        target = _resolve_target_manifest(safe_channel, station_code)
        update_required = False
        if current_version:
            update_required = parse_version_tuple(target.version) > parse_version_tuple(current_version)

        if record_check and station_code and current_version:
            code = station_code.strip()
            if code:
                prev = _NODES.get(code)
                up_to_date = not update_required
                _upsert_node_status(
                    station_code=code,
                    station_id=prev.station_id if prev else None,
                    current_version=current_version,
                    target_version=target.version,
                    channel=target.channel,
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

        return EdgeReleaseOut(
            version=target.version,
            artifact_url=target.artifact_url,
            sha256=target.sha256,
            channel=target.channel,
            min_version=target.min_version,
            notes=target.notes,
            signature=target.signature,
            update_required=update_required,
        )


def publish_release(
    manifest: EdgeReleaseManifest,
    *,
    canary_stations: list[str] | None = None,
    ring1_stations: list[str] | None = None,
) -> EdgeReleaseManifest:
    """Публикует новый релиз для кольца (ring0/canary, ring1, ring2/stable) и обновляет списки станций."""
    ring = normalize_channel(manifest.channel)
    signing_key = get_settings().edge_release_signing_key.strip()
    updates: dict[str, object] = {"channel": ring}
    if signing_key:
        if manifest.signature is not None and manifest.signature.strip():
            if not verify_release_signature(manifest, signing_key):
                raise ValidationError("неверная подпись релиза")
            updates["signature"] = manifest.signature.strip().lower()
        else:
            updates["signature"] = sign_release_manifest(
                manifest.version,
                manifest.sha256,
                manifest.min_version,
                signing_key,
            )
    stored = manifest.model_copy(update=updates)
    with _LOCK:
        _RELEASES[ring] = stored
        _replace_ring_stations(_RING0_STATIONS, canary_stations)
        _replace_ring_stations(_RING1_STATIONS, ring1_stations)
        return stored


def record_heartbeat(hb: EdgeHeartbeatIn) -> EdgeHeartbeatAck:
    """Фиксирует телеметрию узла АГЗС (версия, очередь outbox, статус обновления) и возвращает целевой релиз."""
    with _LOCK:
        release = get_release_for_station(
            channel=hb.channel,
            station_code=hb.station_code,
            current_version=hb.current_version,
        )
        up_to_date = parse_version_tuple(hb.current_version) >= parse_version_tuple(release.version)
        _upsert_node_status(
            station_code=hb.station_code,
            station_id=hb.station_id,
            current_version=hb.current_version,
            target_version=release.version,
            channel=release.channel,
            up_to_date=up_to_date,
            outbox_pending=hb.outbox_pending,
            active_pumps=hb.active_pumps,
            update_status=hb.update_status,
            last_error=hb.last_error,
        )
        return EdgeHeartbeatAck(
            accepted=True,
            update_required=not up_to_date,
            release=release,
        )


def fleet_summary() -> EdgeFleetSummaryOut:
    """Возвращает сводку по всем известным станционным серверам и их версиям."""
    with _LOCK:
        nodes_out: list[EdgeNodeStatus] = []
        up_to_date_count = 0
        for code in sorted(_NODES.keys()):
            node = _NODES[code]
            target = _resolve_target_manifest(node.channel, code)
            is_fresh = parse_version_tuple(node.current_version) >= parse_version_tuple(target.version)
            if is_fresh:
                up_to_date_count += 1
            nodes_out.append(
                node.model_copy(
                    update={
                        "target_version": target.version,
                        "channel": target.channel,
                        "up_to_date": is_fresh,
                    }
                )
            )
        total = len(nodes_out)
        releases_map: dict[str, EdgeReleaseManifest] = {
            "ring0": _RELEASES["ring0"],
            "ring1": _RELEASES["ring1"],
            "ring2": _RELEASES["ring2"],
            "canary": _RELEASES["ring0"],
            "stable": _RELEASES["ring2"],
        }
        return EdgeFleetSummaryOut(
            total_nodes=total,
            up_to_date_nodes=up_to_date_count,
            outdated_nodes=total - up_to_date_count,
            releases=releases_map,
            canary_stations=sorted(_RING0_STATIONS),
            ring1_stations=sorted(_RING1_STATIONS),
            nodes=nodes_out,
        )


def reset_edge_fleet() -> None:
    """Сбрасывает состояние реестра релизов и узлов (для тестов)."""
    with _LOCK:
        _RELEASES.clear()
        _RELEASES.update(_default_releases())
        _RING0_STATIONS.clear()
        _RING1_STATIONS.clear()
        _NODES.clear()
