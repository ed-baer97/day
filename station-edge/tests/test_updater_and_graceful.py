"""Тесты Graceful Shutdown, проверки активного налива и Pull-автообновления station-edge."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    CMD_PARAMS_ASCII,
    CMD_RESET_ASCII,
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    build_test_response_frame,
    parse_iskra_frame,
)
from agzs_edge.main import main
from agzs_edge.monitor import build_shift_snapshot, render_shift_dashboard
from agzs_edge.serial_link import PollRawResult
from agzs_edge.service import StationEdgeService
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker, VpsSendResult
from agzs_edge.tracker import CompletedDispense, PumpDispenseTracker
from agzs_edge.updater import (
    EdgeUpdater,
    ReleaseManifest,
    UpdateProgressState,
    clear_update_state,
    compute_sha256,
    is_newer_version,
    parse_version_tuple,
    read_update_state,
    update_state_path,
    write_update_state,
)


def _make_frame(addr: int, state: str, volume_ml: int, *, price: int = 10000):
    raw = build_test_response_frame(
        address=addr,
        state_code=state,
        error_code="00",
        price_digits=price,
        volume_ml=volume_ml,
    )
    return parse_iskra_frame(raw)


def test_tracker_and_db_active_dispensing_pumps(tmp_path: Path) -> None:
    tracker = PumpDispenseTracker(station_code="AKT-12")
    t0 = datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)

    assert tracker.has_active_sessions() is False
    assert tracker.active_addresses() == ()

    tracker.process_frame(_make_frame(2, STATE_DISPENSING, 5000), observed_at=t0)
    assert tracker.has_active_sessions() is True
    assert tracker.active_addresses() == (2,)

    tracker.process_frame(_make_frame(2, STATE_COMPLETED, 12000), observed_at=t0 + timedelta(seconds=10))
    assert tracker.has_active_sessions() is False

    db_path = tmp_path / "edge.db"
    db = EdgeDatabase(db_path)
    db.update_live_state(_make_frame(1, STATE_DOSE_SET, 20000), observed_at=t0)
    db.update_live_state(_make_frame(2, STATE_DISPENSING, 4500), observed_at=t0)
    db.update_live_state(_make_frame(3, STATE_IDLE, 0), observed_at=t0)
    # Устаревшая запись для колонки 4
    db.update_live_state(_make_frame(4, STATE_DISPENSING, 1000), observed_at=t0 - timedelta(seconds=120))

    ro = EdgeDatabase(db_path, read_only=True)
    assert ro.active_dispensing_pumps(max_age_sec=30.0, now=t0 + timedelta(seconds=5)) == [1, 2]
    assert ro.active_dispensing_pumps(max_age_sec=0.0, now=t0 + timedelta(seconds=5)) == [1, 2, 4]


def test_graceful_shutdown_waits_for_active_dispense_and_resets(tmp_path: Path) -> None:
    """При request_stop() во время налива '03' сервис не обрывается, а дожидается '07', шлёт 0x37 и синкает."""
    t0 = datetime(2026, 11, 19, 11, 0, 0, tzinfo=timezone.utc)
    sequence = [
        build_test_response_frame(address=1, state_code=STATE_DOSE_SET, error_code="00", price_digits=7200, volume_ml=20000),
        build_test_response_frame(address=1, state_code=STATE_DISPENSING, error_code="00", price_digits=7200, volume_ml=15000),
        build_test_response_frame(address=1, state_code=STATE_DISPENSING, error_code="00", price_digits=7200, volume_ml=9000),
        build_test_response_frame(address=1, state_code=STATE_COMPLETED, error_code="00", price_digits=7200, volume_ml=0),
    ]
    idle_resp = build_test_response_frame(
        address=1, state_code=STATE_IDLE, error_code="00", price_digits=7200, volume_ml=0
    )

    sent_commands: list[int] = []
    synced_payloads: list[dict] = []

    class _ScriptedLink:
        def __init__(self) -> None:
            self.poll_idx = 0
            self.closed = False

        def open(self) -> None:
            return

        def close(self) -> None:
            self.closed = True

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            del checksum_mode
            if self.poll_idx < len(sequence):
                raw = sequence[self.poll_idx]
                self.poll_idx += 1
            else:
                raw = idle_resp
            return PollRawResult(address=address, request_bytes=b"req", response_bytes=raw)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            sent_commands.append(request[3])
            return PollRawResult(address=address, request_bytes=request, response_bytes=idle_resp)

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
        db_path=tmp_path / "graceful.db",
        sync_enabled=True,
        sync_interval_sec=0.0,
        device_token="tok-graceful",
    )
    db = EdgeDatabase(settings.db_path)
    worker = OutboxSyncWorker(
        db,
        vps_base_url=settings.vps_base_url,
        device_token=settings.device_token,
        sender=lambda url, tok, body: (
            synced_payloads.append(json.loads(body))
            or VpsSendResult(ok=True, response_text='{"accepted":true}')
        ),
    )
    link = _ScriptedLink()
    service = StationEdgeService(settings, link=link, db=db, sync_worker=worker)

    # Имитируем приход SIGTERM прямо после 2-го цикла опроса (когда колонка 1 наливает: STATE_DISPENSING)
    orig_poll = service.poll_cycle_once
    poll_count = 0

    def _wrapped_poll() -> list:
        nonlocal poll_count
        poll_count += 1
        res = orig_poll(observed_at=t0 + timedelta(seconds=poll_count))
        if poll_count == 2:
            assert service.tracker.has_active_sessions() is True
            assert service.is_idle_for_update() is False
            service.request_stop()
        return res

    service.poll_cycle_once = _wrapped_poll  # type: ignore[method-assign]
    service.serve(max_cycles=20, graceful_timeout_sec=10.0)

    assert poll_count == 4  # не остановился на 2-м цикле, дождался 4-го (STATE_COMPLETED)
    assert link.closed is True
    assert CMD_RESET_ASCII in sent_commands
    info = db.summary()
    assert info["total_dispenses"] == 1
    assert info["total_dispensed_ml"] == 20000
    assert info["outbox_sent"] == 1
    assert len(synced_payloads) == 1


def test_updater_scenarios_up_to_date_success_sha_fail_busy_and_rollback(tmp_path: Path) -> None:
    assert parse_version_tuple("0.2.10") > parse_version_tuple("0.2.2")
    assert is_newer_version("0.1.0", "0.2.0") is True
    assert is_newer_version("0.2.0", "0.2.0") is False

    db_path = tmp_path / "station.db"
    db_rw = EdgeDatabase(db_path)
    db_ro = EdgeDatabase(db_path, read_only=True)
    releases_dir = tmp_path / "releases"
    settings = EdgeSettings(
        db_path=db_path,
        releases_dir=releases_dir,
        station_code="AKT-TEST-01",
        update_channel="stable",
    )
    heartbeats: list[dict] = []

    def _fake_hb(url, token, **kwargs) -> bool:
        heartbeats.append(kwargs)
        return True

    # 1. Актуальная версия -> up_to_date
    updater_same = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.2.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0-py3-none-any.whl",
            sha256="a" * 64,
        ),
        heartbeat_fn=_fake_hb,
    )
    res_same = updater_same.run_update()
    assert res_same.status == "up_to_date"
    assert heartbeats[-1]["update_status"] == "up_to_date"

    # Готовим реальный .whl-файл и его SHA-256
    wheel_bytes = b"fake-wheel-v0.2.0"
    wheel_sha = hashlib.sha256(wheel_bytes).hexdigest()

    def _download_ok(url: str, dest: Path, *, device_token: str = "") -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_bytes)
        return dest

    # 2. Несовпадение SHA-256 -> failed и битый файл удалён
    updater_bad_sha = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256="f" * 64,
        ),
        artifact_downloader=_download_ok,
        heartbeat_fn=_fake_hb,
    )
    res_bad_sha = updater_bad_sha.run_update()
    assert res_bad_sha.status == "failed"
    assert not (releases_dir / "agzs_edge-0.2.0.whl").exists()

    # 3. Колонка занята наливом -> deferred_busy
    now = datetime.now(timezone.utc)
    db_rw.update_live_state(_make_frame(1, STATE_DISPENSING, 4000), observed_at=now)
    updater_busy = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=wheel_sha,
        ),
        artifact_downloader=_download_ok,
        heartbeat_fn=_fake_hb,
        sleep_fn=lambda _s: None,
    )
    res_busy = updater_busy.run_update(wait_idle_sec=0.0)
    assert res_busy.status == "deferred_busy"
    assert heartbeats[-1]["update_status"] == "deferred_busy"

    # 4. Успешное обновление до 0.2.0
    db_rw.update_live_state(_make_frame(1, STATE_STOPPED, 0), observed_at=now)
    installed: list[str] = []
    restarted: list[str] = []
    updater_ok = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=wheel_sha,
        ),
        artifact_downloader=_download_ok,
        installer_fn=lambda path: installed.append(path.name),
        self_test_fn=lambda: True,
        restart_fn=lambda cmd: restarted.append(cmd),
        heartbeat_fn=_fake_hb,
    )
    res_ok = updater_ok.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res_ok.status == "updated"
    assert installed == ["agzs_edge-0.2.0.whl"]
    assert restarted == ["systemctl restart station-edge.service"]
    assert compute_sha256(Path((releases_dir / "current_wheel.txt").read_text(encoding="utf-8").strip())) == wheel_sha
    assert heartbeats[-1]["current_version"] == "0.2.0"
    assert heartbeats[-1]["update_status"] == "updated"

    # 5. Сбой self-test при попытке 0.3.0 -> автоматический откат на 0.2.0
    wheel_v3_bytes = b"broken-wheel-v0.3.0"
    wheel_v3_sha = hashlib.sha256(wheel_v3_bytes).hexdigest()

    def _download_v3(url: str, dest: Path, *, device_token: str = "") -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_v3_bytes)
        return dest

    rollback_installs: list[str] = []
    rollback_restarts: list[str] = []
    updater_rb = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.2.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.3.0",
            artifact_url="https://example.com/agzs_edge-0.3.0.whl",
            sha256=wheel_v3_sha,
        ),
        artifact_downloader=_download_v3,
        installer_fn=lambda path: rollback_installs.append(path.name),
        self_test_fn=lambda: False,
        restart_fn=lambda cmd: rollback_restarts.append(cmd),
        heartbeat_fn=_fake_hb,
    )
    res_rb = updater_rb.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res_rb.status == "rolled_back"
    assert rollback_installs == ["agzs_edge-0.3.0.whl", "agzs_edge-0.2.0.whl"]
    assert rollback_restarts == ["systemctl restart station-edge.service"]
    assert heartbeats[-1]["update_status"] == "rolled_back"
    assert heartbeats[-1]["current_version"] == "0.2.0"


def test_cli_update_check_command(tmp_path: Path, monkeypatch, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AGZS_DB_PATH={tmp_path / 'cli.db'}\n"
        "AGZS_STATION_CODE=AKT-CLI\n"
        "AGZS_UPDATE_CHANNEL=canary\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agzs_edge.updater.fetch_release_manifest",
        lambda *a, **kw: ReleaseManifest(
            version="9.9.9",
            artifact_url="https://example.com/agzs_edge-9.9.9.whl",
            sha256="b" * 64,
            channel="canary",
        ),
    )

    rc = main(["--env-file", str(env_file), "update", "--check"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "[UPDATE_AVAILABLE]" in captured.out
    assert "9.9.9" in captured.out


def test_is_station_idle_for_update_checks_quiet_window(tmp_path: Path) -> None:
    db_path = tmp_path / "idle.db"
    db = EdgeDatabase(db_path)
    ro = EdgeDatabase(db_path, read_only=True)
    t0 = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)

    # Пустая БД без заправок и активных колонок -> станция в простое
    idle, _ = ro.is_station_idle_for_update(min_quiet_sec=60.0, now=t0)
    assert idle is True

    # Если колонка наливает -> простой False
    db.update_live_state(_make_frame(1, STATE_DISPENSING, 3000), observed_at=t0)
    idle_disp, msg_disp = ro.is_station_idle_for_update(min_quiet_sec=60.0, now=t0 + timedelta(seconds=5))
    assert idle_disp is False
    assert "колонках [1]" in msg_disp

    # Колонка завершила налив и перешла в IDLE, в dispenses записана заправка в t0 + 10s
    db.update_live_state(_make_frame(1, STATE_IDLE, 0), observed_at=t0 + timedelta(seconds=10))
    db.record_completed_dispense(
        CompletedDispense(
            external_txn_id="quiet-txn-1",
            pump_address=1,
            mode="dose",
            preset_ml=10000,
            dispensed_ml=10000,
            volume_liters=10.0,
            price_kzt_per_liter=72.0,
            final_state_code=STATE_COMPLETED,
            error_code="00",
            started_at=t0,
            finished_at=t0 + timedelta(seconds=10),
            last_raw_frame_hex="01 31 34",
        ),
        station_id="a2222222-2222-2222-2222-222222222201",
        dispenser_id="d2222222-2222-2222-2222-222222222201",
        tank_id="b2222222-2222-2222-2222-222222222201",
        now=t0 + timedelta(seconds=10),
    )

    # Через 15 секунд после окончания налива (< 60 с тишины) -> обновление ещё ждёт простоя
    idle_soon, msg_soon = ro.is_station_idle_for_update(min_quiet_sec=60.0, now=t0 + timedelta(seconds=25))
    assert idle_soon is False
    assert "простоя" in msg_soon

    # Через 65 секунд после окончания налива -> простой подтверждён
    idle_later, _ = ro.is_station_idle_for_update(min_quiet_sec=60.0, now=t0 + timedelta(seconds=75))
    assert idle_later is True


def test_power_loss_recovery_and_tty1_update_banner(tmp_path: Path) -> None:
    """При отключении света во время обновления монитор показывает блокировку, а при старте обновление завершается."""
    db_path = tmp_path / "station_edge.db"
    db_rw = EdgeDatabase(db_path)
    db_ro = EdgeDatabase(db_path, read_only=True)
    db_rw.update_live_state(
        _make_frame(1, STATE_IDLE, 0),
        observed_at=datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc),
    )

    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = releases_dir / "agzs_edge-0.2.0.whl"
    wheel_bytes = b"wheel-0.2.0-content"
    wheel_path.write_bytes(wheel_bytes)
    wheel_sha = hashlib.sha256(wheel_bytes).hexdigest()

    settings = EdgeSettings(
        db_path=db_path,
        releases_dir=releases_dir,
        pump_addresses=(1,),
        station_code="AKT-RECOVERY",
        update_channel="ring2",
        update_idle_quiet_sec=0.0,
    )

    # Имитируем внезапное выключение питания прямо в момент phase="installing"
    write_update_state(
        settings,
        UpdateProgressState(
            in_progress=True,
            phase="installing",
            current_version="0.1.0",
            target_version="0.2.0",
            channel="ring2",
            message="ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=wheel_sha,
            artifact_path=str(wheel_path),
        ),
    )
    assert update_state_path(settings).is_file()

    # 1. На экране бесправного пользователя /dev/tty1 горит окно блокировки и статус колонки ОБНОВЛЕНИЕ
    snap_during = build_shift_snapshot(db_ro, settings)
    assert snap_during.update_state is not None
    assert snap_during.pumps[0].state_label_ru == "ОБНОВЛЕНИЕ"
    rendered_during = render_shift_dashboard(snap_during, kiosk=True)
    assert "ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ" in rendered_during
    for line in rendered_during.splitlines():
        if line.startswith(("╔", "║", "╚")):
            assert len(line) == 80

    # 2. После включения питания запускается апдейтер (даже если VPS недоступен!) и завершает обновление
    installed: list[str] = []
    restarted: list[str] = []
    heartbeats: list[dict] = []

    def _offline_manifest(*_a, **_kw):
        raise RuntimeError("VPS offline")

    updater = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=_offline_manifest,
        installer_fn=lambda path: installed.append(path.name),
        self_test_fn=lambda: True,
        restart_fn=lambda cmd: restarted.append(cmd),
        heartbeat_fn=lambda _u, _t, **kw: (heartbeats.append(kw) or True),
    )
    res = updater.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res.status == "updated"
    assert installed == ["agzs_edge-0.2.0.whl"]
    assert restarted == ["systemctl restart station-edge.service"]
    assert read_update_state(settings) is None
    assert heartbeats[-1]["update_status"] == "updated"

    # 3. После завершения обновления окно на /dev/tty1 исчезает, колонка снова показывает "Готова"
    snap_after = build_shift_snapshot(db_ro, settings)
    assert snap_after.update_state is None
    assert snap_after.pumps[0].state_label_ru == "Готова"
    rendered_after = render_shift_dashboard(snap_after, kiosk=True)
    assert "ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ" not in rendered_after
    assert "Кнопки ПУСК на колонках временно заблокированы" not in rendered_after


def test_physical_pump_buttons_locked_during_update_and_restored_on_start(tmp_path: Path) -> None:
    """На время обновления сервис шлёт 0.17 (блок кнопок), а при старте/завершении восстанавливает 0.18."""
    idle_resp = build_test_response_frame(
        address=1, state_code=STATE_IDLE, error_code="00", price_digits=7200, volume_ml=0
    )
    disp_resp = build_test_response_frame(
        address=1, state_code=STATE_DISPENSING, error_code="00", price_digits=7200, volume_ml=5000
    )
    done_resp = build_test_response_frame(
        address=1, state_code=STATE_COMPLETED, error_code="00", price_digits=7200, volume_ml=0
    )

    param_codes_sent: list[str] = []

    class _ButtonTrackingLink:
        def __init__(self, frames: list[bytes]) -> None:
            self.frames = frames
            self.idx = 0

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            del checksum_mode
            raw = self.frames[min(self.idx, len(self.frames) - 1)]
            self.idx += 1
            return PollRawResult(address=address, request_bytes=b"req", response_bytes=raw)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            if request[3] == CMD_PARAMS_ASCII:
                param_codes_sent.append(request[5:11].decode("ascii"))
            return PollRawResult(address=address, request_bytes=request, response_bytes=idle_resp)

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        auto_reset_on_stop=True,
        auto_reset_delay_sec=0.0,
        lock_buttons_on_update=True,
        pump_buttons_mode="lock-reset",
        db_path=tmp_path / "buttons.db",
        sync_enabled=False,
    )
    db = EdgeDatabase(settings.db_path)

    # 1. Идёт налив -> появляется update_state -> 0.17 НЕ шлётся, пока налив не завершится
    link = _ButtonTrackingLink([disp_resp, done_resp, idle_resp])
    service = StationEdgeService(settings, link=link, db=db)

    service.poll_cycle_once()  # STATE_DISPENSING
    write_update_state(
        settings,
        UpdateProgressState(
            in_progress=True,
            phase="installing",
            current_version="0.1.0",
            target_version="0.2.0",
            channel="ring2",
            message="ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ",
        ),
    )
    assert param_codes_sent == []  # во время активного налива кнопки ещё не блокировались

    service.poll_cycle_once()  # STATE_COMPLETED -> авто-сброс 0x37 -> колонка свободна -> сразу 0.17
    assert param_codes_sent == ["000017"]

    # Снимаем файл состояния обновления (будто обновление завершилось без рестарта) -> возврат 0.18
    clear_update_state(settings)
    service.poll_cycle_once()
    assert param_codes_sent == ["000017", "000016"]

    # 2. Старт новой службы включает кнопки 000016 и не блокирует СБРОС через 000018
    param_codes_sent.clear()
    restarted_service = StationEdgeService(settings, link=_ButtonTrackingLink([idle_resp]), db=db)
    restarted_service.serve(max_cycles=1)
    assert param_codes_sent == ["000016"]

    # 3. Кадр 0x50 (СБРОС выключен) получает 000016 без 0x37.
    # Кадр 0x70 (ПУСК/СТОП и СБРОС уже включены) команду не получает.
    defaults = EdgeSettings()
    assert defaults.auto_reset_on_stop is True
    assert defaults.read_only is False
    assert defaults.lock_buttons_on_update is False
    assert defaults.auto_reset_stopped_delay_sec == 0.0
    assert defaults.pump_buttons_mode == "enable"
    from agzs_edge.iskra import SOH, ETX, STX, CMD_TEST_ASCII, compute_bcc

    def _live_05_frame(byte17: int) -> bytes:
        body = (
            b"01"
            + bytes([CMD_TEST_ASCII, STX])
            + b"007200"
            + b"000000"
            + bytes([byte17, 0x8A])
            + b"05"
            + bytes([ETX])
        )
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    live_05_enabled = _live_05_frame(0x70)
    live_05_locked_rst = _live_05_frame(0x50)
    default_safe_settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        auto_reset_on_stop=True,
        db_path=tmp_path / "buttons_default_safe.db",
        sync_enabled=False,
    )
    param_codes_sent.clear()
    StationEdgeService(default_safe_settings, link=_ButtonTrackingLink([live_05_locked_rst])).serve(max_cycles=1)
    assert param_codes_sent == ["000016"]

    start_off = _live_05_frame(0x10)
    param_codes_sent.clear()
    StationEdgeService(
        EdgeSettings(
            source_mode="serial",
            pump_addresses=(1,),
            poll_interval_sec=0.0,
            auto_reset_on_stop=True,
            db_path=tmp_path / "buttons_start_off.db",
            sync_enabled=False,
        ),
        link=_ButtonTrackingLink([start_off]),
    ).serve(max_cycles=1)
    assert param_codes_sent == ["000016"]

    explicit_settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        auto_reset_on_stop=True,
        lock_buttons_on_update=True,
        db_path=tmp_path / "buttons_live.db",
        sync_enabled=False,
    )
    param_codes_sent.clear()
    StationEdgeService(explicit_settings, link=_ButtonTrackingLink([live_05_enabled])).serve(max_cycles=1)
    assert param_codes_sent == []

    param_codes_sent.clear()
    StationEdgeService(explicit_settings, link=_ButtonTrackingLink([live_05_locked_rst])).serve(max_cycles=1)
    assert param_codes_sent == ["000016"]


def test_updater_calls_lock_and_unlock_pumps_on_success_and_rollback(tmp_path: Path) -> None:
    db_path = tmp_path / "upd_lock.db"
    EdgeDatabase(db_path)
    db_ro = EdgeDatabase(db_path, read_only=True)
    releases_dir = tmp_path / "releases"
    settings = EdgeSettings(
        db_path=db_path,
        releases_dir=releases_dir,
        station_code="AKT-LOCK",
        update_idle_quiet_sec=0.0,
    )

    events: list[str] = []
    wheel_v2 = b"wheel-v2"
    sha_v2 = hashlib.sha256(wheel_v2).hexdigest()

    def _dl_v2(url: str, dest: Path, *, device_token: str = "") -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_v2)
        return dest

    updater_ok = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=sha_v2,
        ),
        artifact_downloader=_dl_v2,
        installer_fn=lambda p: events.append(f"install:{p.name}"),
        self_test_fn=lambda: True,
        restart_fn=lambda cmd: events.append(f"restart:{cmd}"),
        heartbeat_fn=lambda *a, **kw: True,
        lock_pumps_fn=lambda: events.append("lock_0.17"),
        unlock_pumps_fn=lambda: events.append("unlock_0.18"),
    )
    res_ok = updater_ok.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res_ok.status == "updated"
    assert events == [
        "lock_0.17",
        "install:agzs_edge-0.2.0.whl",
        "restart:systemctl restart station-edge.service",
        "unlock_0.18",
    ]

    # При сбое self-test и откате кнопки тоже блокируются до и разблокируются после отката
    events.clear()
    wheel_v3 = b"wheel-v3-bad"
    sha_v3 = hashlib.sha256(wheel_v3).hexdigest()

    def _dl_v3(url: str, dest: Path, *, device_token: str = "") -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_v3)
        return dest

    updater_rb = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.2.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.3.0",
            artifact_url="https://example.com/agzs_edge-0.3.0.whl",
            sha256=sha_v3,
        ),
        artifact_downloader=_dl_v3,
        installer_fn=lambda p: events.append(f"install:{p.name}"),
        self_test_fn=lambda: False,
        restart_fn=lambda cmd: events.append(f"restart:{cmd}"),
        heartbeat_fn=lambda *a, **kw: True,
        lock_pumps_fn=lambda: events.append("lock_0.17"),
        unlock_pumps_fn=lambda: events.append("unlock_0.18"),
    )
    res_rb = updater_rb.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res_rb.status == "rolled_back"
    assert events == [
        "lock_0.17",
        "install:agzs_edge-0.3.0.whl",
        "install:agzs_edge-0.2.0.whl",
        "restart:systemctl restart station-edge.service",
        "unlock_0.18",
    ]


def test_updater_hmac_signature_verification_and_resume(tmp_path: Path) -> None:
    """Подпись HMAC-SHA256 блокирует подмену релиза при старте, при check_only и при resume после сбоя."""
    from agzs_edge.updater import canonical_release_payload, sign_release_manifest

    db_path = tmp_path / "sig.db"
    EdgeDatabase(db_path)
    db_ro = EdgeDatabase(db_path, read_only=True)
    releases_dir = tmp_path / "releases"
    signing_key = "super-secret-ota-key"

    wheel_v2 = b"signed-wheel-0.2.0"
    sha_v2 = hashlib.sha256(wheel_v2).hexdigest()
    good_sig = sign_release_manifest("0.2.0", sha_v2, "0.1.0", signing_key)
    assert canonical_release_payload("0.2.0", sha_v2, "0.1.0") == (
        f"0.2.0\n{sha_v2}\n0.1.0".encode("utf-8")
    )

    def _download(url: str, dest: Path, *, device_token: str = "") -> Path:
        del url, device_token
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_v2)
        return dest

    settings = EdgeSettings(
        db_path=db_path,
        releases_dir=releases_dir,
        station_code="AKT-SIG",
        update_idle_quiet_sec=0.0,
        release_signing_key=signing_key,
        require_release_signature=True,
    )

    # 1. Отсутствующая или поддельная подпись отклоняется ДО скачивания
    download_calls: list[str] = []
    forged_updater = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=sha_v2,
            min_version="0.1.0",
            signature="0" * 64,
        ),
        artifact_downloader=lambda u, d, **kw: download_calls.append(u) or _download(u, d),
        heartbeat_fn=lambda *a, **kw: True,
    )
    assert forged_updater.run_update(check_only=True).status == "failed"
    forged_res = forged_updater.run_update()
    assert forged_res.status == "failed"
    assert "подпись" in forged_res.message.lower()
    assert download_calls == []

    # 2. Верная подпись проходит проверку, загружает и устанавливает .whl
    installed: list[str] = []
    ok_updater = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=sha_v2,
            min_version="0.1.0",
            signature=good_sig,
        ),
        artifact_downloader=_download,
        installer_fn=lambda p: installed.append(p.name),
        self_test_fn=lambda: True,
        restart_fn=lambda _cmd: None,
        heartbeat_fn=lambda *a, **kw: True,
        lock_pumps_fn=lambda: None,
        unlock_pumps_fn=lambda: None,
    )
    ok_res = ok_updater.run_update()
    assert ok_res.status == "updated"
    assert installed == ["agzs_edge-0.2.0.whl"]

    # 3. Если require_release_signature=True, но ключ не задан на станции — обновление запрещено
    nokey_settings = EdgeSettings(
        db_path=db_path,
        releases_dir=releases_dir,
        station_code="AKT-NOKEY",
        require_release_signature=True,
        release_signing_key="",
    )
    nokey_updater = EdgeUpdater(
        nokey_settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=sha_v2,
            min_version="0.1.0",
            signature=good_sig,
        ),
        heartbeat_fn=lambda *a, **kw: True,
    )
    assert nokey_updater.run_update().status == "failed"

    # 4. Подменённый state после отключения питания с невалидной подписью отклоняется и удаляет .whl
    forged_whl = releases_dir / "agzs_edge-0.9.0.whl"
    forged_whl.parent.mkdir(parents=True, exist_ok=True)
    forged_whl.write_bytes(b"tampered")
    write_update_state(
        settings,
        UpdateProgressState(
            in_progress=True,
            phase="installing",
            current_version="0.1.0",
            target_version="0.9.0",
            channel="ring2",
            message="test",
            sha256=hashlib.sha256(b"tampered").hexdigest(),
            min_version="0.1.0",
            signature="deadbeef" * 8,
            artifact_path=str(forged_whl),
        ),
    )
    installed.clear()
    resume_updater = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        installer_fn=lambda p: installed.append(p.name),
        self_test_fn=lambda: True,
        heartbeat_fn=lambda *a, **kw: True,
        lock_pumps_fn=lambda: None,
        unlock_pumps_fn=lambda: None,
    )
    resume_res = resume_updater.run_update()
    assert resume_res.status == "failed"
    assert not forged_whl.exists()
    assert installed == []


def test_updater_does_not_import_service_cycle() -> None:
    """updater.py не должен импортировать agzs_edge.service (отсутствие цикла модулей)."""
    import ast

    updater_path = Path(__file__).resolve().parents[1] / "agzs_edge" / "updater.py"
    tree = ast.parse(updater_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(mod == "agzs_edge.service" or mod.startswith("agzs_edge.service.") for mod in imported)


def test_restore_pump_buttons_retries_after_partial_error(tmp_path: Path) -> None:
    """Если восстановление кнопок (0.16) упало с ошибкой COM на цикле 1, цикл 2 повторяет попытку."""
    from agzs_edge.iskra import CMD_TEST_ASCII, ETX, SOH, STX, compute_bcc

    def _live_05(byte17: int) -> bytes:
        body = (
            b"01"
            + bytes([CMD_TEST_ASCII, STX])
            + b"007200"
            + b"000000"
            + bytes([byte17, 0x8A])
            + b"05"
            + bytes([ETX])
        )
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    frame_locked_rst = _live_05(0x50)
    frame_enabled = _live_05(0x70)

    class _FlakyButtonLink:
        def __init__(self) -> None:
            self.poll_calls = 0
            self.param_calls: list[str] = []

        def open(self) -> None:
            return

        def close(self) -> None:
            return

        def poll_test(self, address: int, *, checksum_mode: str | None = None) -> PollRawResult:
            del checksum_mode
            self.poll_calls += 1
            raw = frame_locked_rst if self.poll_calls <= 2 else frame_enabled
            return PollRawResult(address=address, request_bytes=b"req", response_bytes=raw)

        def send_command(self, address: int, request: bytes) -> PollRawResult:
            if request[3] == CMD_PARAMS_ASCII:
                self.param_calls.append(request[5:11].decode("ascii"))
                if len(self.param_calls) == 1:
                    return PollRawResult(
                        address=address,
                        request_bytes=request,
                        response_bytes=b"",
                        error_message="temporary COM error",
                    )
            return PollRawResult(address=address, request_bytes=request, response_bytes=frame_enabled)

    settings = EdgeSettings(
        source_mode="serial",
        pump_addresses=(1,),
        poll_interval_sec=0.0,
        read_only=False,
        lock_buttons_on_update=True,
        pump_buttons_mode="enable",
        db_path=tmp_path / "retry_buttons.db",
        sync_enabled=False,
    )
    link = _FlakyButtonLink()
    svc = StationEdgeService(settings, link=link, db=EdgeDatabase(settings.db_path))
    svc._restore_buttons_pending = True  # noqa: SLF001

    svc.poll_cycle_once()  # попытка 1 -> ошибка COM на 0.16
    assert link.param_calls == ["000016"]
    assert svc._restore_buttons_pending is True  # noqa: SLF001

    svc.poll_cycle_once()  # попытка 2 -> повтор 0.16 успешен
    assert link.param_calls == ["000016", "000016"]
    assert svc._restore_buttons_pending is False  # noqa: SLF001

    svc.poll_cycle_once()  # попытка 3 -> биты уже 0x70, повторного спама нет
    assert link.param_calls == ["000016", "000016"]


def test_write_update_state_refreshes_updated_at_and_skips_direct_port_after_restart(tmp_path: Path, monkeypatch) -> None:
    """write_update_state всегда обновляет updated_at после replace(), а при restart_cmd апдейтер не лезет в порт."""
    from dataclasses import replace

    db_path = tmp_path / "upd_ts.db"
    EdgeDatabase(db_path)
    db_ro = EdgeDatabase(db_path, read_only=True)
    settings = EdgeSettings(
        db_path=db_path,
        releases_dir=tmp_path / "releases",
        lock_buttons_on_update=True,
        read_only=False,
        update_idle_quiet_sec=0.0,
    )
    initial = UpdateProgressState(
        in_progress=True,
        phase="installing",
        current_version="0.1.0",
        target_version="0.2.0",
        channel="stable",
        message="test",
        updated_at="2020-01-01T00:00:00+00:00",
    )
    write_update_state(settings, replace(initial, buttons_locked=True))
    loaded = read_update_state(settings)
    assert loaded is not None
    assert loaded.buttons_locked is True
    assert loaded.updated_at != "2020-01-01T00:00:00+00:00"
    clear_update_state(settings)

    wheel_v2 = b"wheel-v2-norace"
    sha_v2 = hashlib.sha256(wheel_v2).hexdigest()
    send_calls: list[str] = []
    monkeypatch.setattr(EdgeUpdater, "_send_buttons_param", lambda self, code: send_calls.append(code) or True)

    def _dl(url: str, dest: Path, *, device_token: str = "") -> Path:
        del url, device_token
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel_v2)
        return dest

    updater = EdgeUpdater(
        settings,
        db=db_ro,
        current_version="0.1.0",
        manifest_fetcher=lambda *a, **kw: ReleaseManifest(
            version="0.2.0",
            artifact_url="https://example.com/agzs_edge-0.2.0.whl",
            sha256=sha_v2,
        ),
        artifact_downloader=_dl,
        installer_fn=lambda _p: None,
        self_test_fn=lambda: True,
        restart_fn=lambda _cmd: None,
        heartbeat_fn=lambda *a, **kw: True,
    )
    res = updater.run_update(restart_cmd="systemctl restart station-edge.service")
    assert res.status == "updated"
    assert send_calls == ["0.17"]



