"""Тесты централизованного управления релизами (3 кольца: ring0, ring1, ring2) и телеметрии парка АГЗС."""

import hmac

import pytest

from app.auth import require_admin
from app.config import get_settings
from app.domain.errors import ValidationError
from app.routers.ingest import (
    get_edge_fleet,
    get_edge_release,
    post_edge_heartbeat,
    put_edge_release,
    router as ingest_router,
)
from app.schemas.ingest import EdgeHeartbeatIn, EdgeReleaseManifest
from app.services.edge_fleet import reset_edge_fleet, sign_release_manifest


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


def test_edge_release_signing_and_admin_route_guard(monkeypatch):
    # 1. Проверяем, что PUT /edge/release и GET /edge/fleet защищены именно require_admin (а не require_device)
    by_path_method = {
        (route.path, tuple(sorted(route.methods))): [dep.call for dep in route.dependant.dependencies]
        for route in ingest_router.routes
    }
    assert require_admin in by_path_method[("/ingest/edge/release", ("PUT",))]
    assert require_admin in by_path_method[("/ingest/edge/fleet", ("GET",))]
    assert require_admin not in by_path_method[("/ingest/edge/release", ("GET",))]
    assert require_admin not in by_path_method[("/ingest/edge/heartbeat", ("POST",))]

    # 2. Проверяем HMAC-SHA256 подпись релиза при заданном EDGE_RELEASE_SIGNING_KEY
    monkeypatch.setenv("EDGE_RELEASE_SIGNING_KEY", "fleet-secret-key")
    get_settings.cache_clear()
    try:
        sha = "d" * 64
        auto_signed = put_edge_release(
            EdgeReleaseManifest(
                version="0.4.0",
                artifact_url="https://cdn.example.com/agzs_edge-0.4.0-py3-none-any.whl",
                sha256=sha,
                channel="ring0",
                min_version="0.2.0",
            ),
            _="admin",
        )
        expected = sign_release_manifest("0.4.0", sha, "0.2.0", "fleet-secret-key")
        assert auto_signed.signature is not None
        assert hmac.compare_digest(auto_signed.signature, expected)

        fetched = get_edge_release(channel="ring0", _=None)
        assert fetched.signature == expected

        # Поддельная подпись отклоняется с 422 ValidationError
        with pytest.raises(ValidationError) as exc:
            put_edge_release(
                EdgeReleaseManifest(
                    version="0.4.1",
                    artifact_url="https://cdn.example.com/agzs_edge-0.4.1-py3-none-any.whl",
                    sha256=sha,
                    channel="ring0",
                    signature="0" * 64,
                ),
                _="admin",
            )
        assert exc.value.status_code == 422

        # Корректная внешняя подпись принимается
        ext_sig = sign_release_manifest("0.4.2", sha, None, "fleet-secret-key")
        published = put_edge_release(
            EdgeReleaseManifest(
                version="0.4.2",
                artifact_url="https://cdn.example.com/agzs_edge-0.4.2-py3-none-any.whl",
                sha256=sha,
                channel="ring2",
                signature=ext_sig.upper(),
            ),
            _="admin",
        )
        assert published.signature == ext_sig
    finally:
        get_settings.cache_clear()


def test_edge_fleet_persists_and_restores_via_memory_state(tmp_path, monkeypatch):
    from app.services import boot

    state_file = tmp_path / "fleet_state.json"
    monkeypatch.setenv("STATE_PATH", str(state_file))
    monkeypatch.setenv("ACCOUNT_STORE", "memory")
    get_settings.cache_clear()
    try:
        sha = "e" * 64
        put_edge_release(
            EdgeReleaseManifest(
                version="0.5.0",
                artifact_url="https://cdn.example.com/agzs_edge-0.5.0-py3-none-any.whl",
                sha256=sha,
                channel="ring0",
                notes="canary persist",
            ),
            canary_stations=["AKT-PERSIST-1"],
            _=None,
        )
        post_edge_heartbeat(
            EdgeHeartbeatIn(
                station_code="AKT-PERSIST-1",
                current_version="0.5.0",
                channel="ring0",
                outbox_pending=2,
                active_pumps=0,
                update_status="updated",
            ),
            _=None,
        )
        assert state_file.is_file()

        reset_edge_fleet()
        assert get_edge_fleet(_=None).total_nodes == 0
        assert get_edge_release(channel="ring0", station_code="AKT-PERSIST-1", _=None).version == "0.1.0"

        boot.restore_memory_state()
        restored = get_edge_fleet(_=None)
        assert restored.canary_stations == ["AKT-PERSIST-1"]
        assert restored.releases["ring0"].version == "0.5.0"
        assert restored.total_nodes == 1
        assert restored.nodes[0].station_code == "AKT-PERSIST-1"
        assert restored.nodes[0].outbox_pending == 2
    finally:
        get_settings.cache_clear()
