"""Тесты централизованного управления релизами (3 кольца: ring0, ring1, ring2) и телеметрии парка АГЗС."""

import pytest

from app.routers.ingest import (
    get_edge_fleet,
    get_edge_release,
    post_edge_heartbeat,
    put_edge_release,
)
from app.schemas.ingest import EdgeHeartbeatIn, EdgeReleaseManifest
from app.services.edge_fleet import reset_edge_fleet


@pytest.fixture(autouse=True)
def _clean_fleet():
    reset_edge_fleet()
    yield
    reset_edge_fleet()


def test_three_ring_rollout_and_fleet_heartbeat():
    sha_v2 = "a" * 64
    sha_v3 = "b" * 64

    # 1. Кольцо 0 (canary): 1–2 станции рядом с инженером получают 0.3.0
    r0 = put_edge_release(
        EdgeReleaseManifest(
            version="0.3.0",
            artifact_url="https://cdn.example.com/agzs_edge-0.3.0-py3-none-any.whl",
            sha256=sha_v3,
            channel="ring0",
            notes="Кольцо 0: обкатка сутки рядом с инженером",
        ),
        canary_stations=["AKT-R0-1", "AKT-R0-2"],
        _=None,
    )
    assert r0.version == "0.3.0"
    assert r0.channel == "ring0"

    # 2. Кольцо 1 (10% станций): обкатка 1 смену на версии 0.2.0
    r1 = put_edge_release(
        EdgeReleaseManifest(
            version="0.2.0",
            artifact_url="https://cdn.example.com/agzs_edge-0.2.0-py3-none-any.whl",
            sha256=sha_v2,
            channel="ring1",
            notes="Кольцо 1: 10% станций, обкатка 1 смену",
        ),
        ring1_stations=["AKT-R1-1"],
        _=None,
    )
    assert r1.version == "0.2.0"
    assert r1.channel == "ring1"

    # 3. Станции запрашивают релизы (даже при channel="stable" в локальном .env)
    rel_r0 = get_edge_release(
        channel="stable",
        station_code="AKT-R0-1",
        current_version="0.1.0",
        outbox_pending=0,
        _=None,
    )
    assert rel_r0.version == "0.3.0"
    assert rel_r0.channel == "ring0"
    assert rel_r0.update_required is True

    rel_r1 = get_edge_release(
        channel="stable",
        station_code="AKT-R1-1",
        current_version="0.1.0",
        outbox_pending=0,
        _=None,
    )
    assert rel_r1.version == "0.2.0"
    assert rel_r1.channel == "ring1"
    assert rel_r1.update_required is True

    rel_r2 = get_edge_release(
        channel="stable",
        station_code="AKT-R2-099",
        current_version="0.1.0",
        outbox_pending=0,
        _=None,
    )
    assert rel_r2.version == "0.1.0"
    assert rel_r2.channel == "ring2"
    assert rel_r2.update_required is False

    # 4. Станции присылают heartbeat
    ack_r0 = post_edge_heartbeat(
        EdgeHeartbeatIn(
            station_code="AKT-R0-1",
            current_version="0.3.0",
            channel="ring0",
            outbox_pending=0,
            active_pumps=0,
            update_status="updated",
        ),
        _=None,
    )
    assert ack_r0.accepted is True
    assert ack_r0.update_required is False

    ack_r1 = post_edge_heartbeat(
        EdgeHeartbeatIn(
            station_code="AKT-R1-1",
            current_version="0.2.0",
            channel="ring1",
            outbox_pending=1,
            active_pumps=0,
            update_status="updated",
        ),
        _=None,
    )
    assert ack_r1.update_required is False

    ack_r2 = post_edge_heartbeat(
        EdgeHeartbeatIn(
            station_code="AKT-R2-099",
            current_version="0.1.0",
            channel="ring2",
            outbox_pending=4,
            active_pumps=0,
            update_status="up_to_date",
        ),
        _=None,
    )
    assert ack_r2.update_required is False

    # 5. Выкатываем 0.2.0 в Кольцо 2 (остальные 90%, обновление во время простоя)
    put_edge_release(
        EdgeReleaseManifest(
            version="0.2.0",
            artifact_url="https://cdn.example.com/agzs_edge-0.2.0-py3-none-any.whl",
            sha256=sha_v2,
            channel="ring2",
            notes="Кольцо 2: массовая раскатка во время простоя",
        ),
        _=None,
    )

    fleet = get_edge_fleet(_=None)
    assert fleet.total_nodes == 3
    assert fleet.up_to_date_nodes == 2
    assert fleet.outdated_nodes == 1
    assert fleet.canary_stations == ["AKT-R0-1", "AKT-R0-2"]
    assert fleet.ring1_stations == ["AKT-R1-1"]
    assert "canary" in fleet.releases and "stable" in fleet.releases
    by_code = {n.station_code: n for n in fleet.nodes}
    assert by_code["AKT-R0-1"].up_to_date is True
    assert by_code["AKT-R1-1"].up_to_date is True
    assert by_code["AKT-R2-099"].up_to_date is False
    assert by_code["AKT-R2-099"].target_version == "0.2.0"
