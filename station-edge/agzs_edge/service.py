"""Главный сервис станционного узла: цикл опроса АСКА-02, запись в SQLite и отправка на VPS."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    STATE_COMPLETED,
    IskraFrameError,
    IskraTelemetryFrame,
    build_reset_command,
    parse_iskra_frame,
)
from agzs_edge.serial_link import AskaLink, EmulatorAskaLink, SerialAskaLink
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker, probe_vps_link
from agzs_edge.tracker import CompletedDispense, PumpDispenseTracker

logger = logging.getLogger(__name__)


def build_link(settings: EdgeSettings) -> AskaLink:
    if settings.source_mode == "emulator":
        return EmulatorAskaLink(layout=settings.layout)
    return SerialAskaLink(
        port=settings.serial_port,
        baudrate=settings.serial_baudrate,
        timeout_sec=settings.serial_timeout_sec,
        layout=settings.layout,
    )


class StationEdgeService:
    """Координирует опрос колонок УЗГС-01 через АСКА-02, трекер налива, БД и синхронизацию с VPS."""

    def __init__(
        self,
        settings: EdgeSettings,
        *,
        link: AskaLink | None = None,
        db: EdgeDatabase | None = None,
        sync_worker: OutboxSyncWorker | None = None,
    ) -> None:
        self.settings = settings
        self.link = link or build_link(settings)
        self.db = db or EdgeDatabase(settings.db_path)
        self.tracker = PumpDispenseTracker(station_code=settings.station_code)
        self.sync_worker = sync_worker or OutboxSyncWorker(
            self.db,
            vps_base_url=settings.vps_base_url,
            device_token=settings.device_token,
        )
        self._last_sync_ts = 0.0
        self._last_seen: dict[int, tuple[str, str, int]] = {}
        self._stop_07_since: dict[int, float] = {}

    def poll_cycle_once(self, *, observed_at: datetime | None = None) -> list[CompletedDispense]:
        """Опрашивает все адреса из `settings.pump_addresses` по одному разу (команда «Тест»)."""
        closed_dispenses: list[CompletedDispense] = []
        now = observed_at or datetime.now(timezone.utc)

        for address in self.settings.pump_addresses:
            raw_res = self.link.poll_test(address)
            if not raw_res.has_response:
                # Не подставляем газ=0 на VPS; помечаем отсутствие связи для оператора.
                self.db.mark_no_response(address, observed_at=now)
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=b"",
                    valid=False,
                    note=raw_res.error_message or "нет ответа от УЗГС-01",
                )
                continue

            try:
                frame = parse_iskra_frame(raw_res.response_bytes, self.settings.layout)
            except IskraFrameError as exc:
                logger.warning("Адрес %d: некорректный кадр (%s)", address, exc)
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=raw_res.response_bytes,
                    valid=False,
                    note=str(exc),
                )
                continue

            if self.settings.save_raw_frames or frame.has_protocol_alarm:
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=raw_res.response_bytes,
                    valid=True,
                    note=f"state={frame.state_code} err={frame.error_code} ml={frame.volume_ml}",
                )

            self.db.update_live_state(frame, observed_at=now)
            signature = (frame.state_code, frame.price_raw, frame.volume_ml)
            if self._last_seen.get(address) != signature:
                self._last_seen[address] = signature
                if frame.completed_volume_ml is not None:
                    logger.info(
                        "Колонка #%d на связи: сост=%s(%s), итог налива=%d мл, цены в кадре нет",
                        address,
                        frame.state_code,
                        frame.state_name,
                        frame.completed_volume_ml,
                    )
                else:
                    logger.info(
                        "Колонка #%d на связи: сост=%s(%s), цена=%.2f ₸/л, объём=%d мл",
                        address,
                        frame.state_code,
                        frame.state_name,
                        frame.price_kzt_per_liter,
                        frame.volume_ml,
                    )
            completed = self.tracker.process_frame(frame, observed_at=now)
            if completed is not None:
                dispenser_id = self.settings.dispenser_uuid(completed.pump_address)
                inserted = self.db.record_completed_dispense(
                    completed,
                    station_id=self.settings.station_id,
                    dispenser_id=dispenser_id,
                    tank_id=self.settings.tank_id or None,
                )
                if inserted:
                    logger.info(
                        "Зафиксирован уход по колонке #%d (%s): %d мл (%.3f л), цена %.2f ₸/л, txn=%s",
                        completed.pump_address,
                        completed.mode,
                        completed.dispensed_ml,
                        completed.volume_liters,
                        completed.price_kzt_per_liter,
                        completed.external_txn_id,
                    )
                    closed_dispenses.append(completed)

            self._maybe_auto_reset(address, frame, completed=completed, observed_at=now)

        return closed_dispenses

    def _maybe_auto_reset(
        self,
        address: int,
        frame: IskraTelemetryFrame,
        *,
        completed: CompletedDispense | None,
        observed_at: datetime,
    ) -> None:
        if frame.state_code != STATE_COMPLETED or frame.valve_open:
            self._stop_07_since.pop(address, None)
            return
        if not self.settings.auto_reset_on_stop:
            return

        now_mono = time.monotonic()
        if completed is not None or self.settings.auto_reset_delay_sec <= 0:
            should_reset = True
        else:
            first_seen = self._stop_07_since.setdefault(address, now_mono)
            should_reset = (now_mono - first_seen) >= self.settings.auto_reset_delay_sec

        if not should_reset:
            return

        self._stop_07_since.pop(address, None)
        req = build_reset_command(address, checksum_mode=self.settings.layout.checksum_mode)
        res = self.link.send_command(address, req)
        logger.info(
            "Колонка #%d: отправлен автоматический СБРОС (0x37) для снятия блокировки после останова 07",
            address,
        )
        if res.has_response:
            try:
                reset_frame = parse_iskra_frame(res.response_bytes, self.settings.layout)
                self.db.update_live_state(reset_frame, observed_at=observed_at)
                self._last_seen[address] = (
                    reset_frame.state_code,
                    reset_frame.price_raw,
                    reset_frame.volume_ml,
                )
            except IskraFrameError as exc:
                logger.warning("Колонка #%d: некорректный ответ на автосброс (%s)", address, exc)
        elif res.error_message:
            logger.warning("Колонка #%d: ошибка при автосбросе (%s)", address, res.error_message)

    def _announce_vps(self) -> None:
        """Один раз при старте проверяет, что центральный сервер узнаёт токен станции."""
        if not self.settings.sync_enabled:
            logger.info("Отправка на центральный сервер выключена")
            return
        result = probe_vps_link(
            self.settings.vps_base_url,
            self.settings.device_token,
            self.settings.tank_id,
        )
        if not result.ok:
            logger.warning(
                "Центральный сервер %s не подтвердил станцию: %s. Наливы останутся в локальной очереди.",
                self.settings.vps_base_url,
                result.error_text,
            )
            return
        remainder = ""
        try:
            body = json.loads(result.response_text)
            liters = body.get("actual_remainder_liters")
            if isinstance(liters, (int, float)):
                remainder = f", остаток резервуара {liters:g} л"
        except json.JSONDecodeError:
            pass
        logger.info(
            "Центральный сервер %s принял станцию (HTTP %s%s). Закрытый налив колонки уйдёт в книгу резервуара.",
            self.settings.vps_base_url,
            result.status_code,
            remainder,
        )

    def maybe_sync_outbox(self, *, force: bool = False) -> tuple[int, int]:
        if not self.settings.sync_enabled:
            return (0, 0)
        now_mono = time.monotonic()
        if not force and (now_mono - self._last_sync_ts) < self.settings.sync_interval_sec:
            return (0, 0)
        self._last_sync_ts = now_mono
        return self.sync_worker.flush_due()

    def serve(self, *, max_cycles: int | None = None) -> None:
        """Непрерывный цикл работы на станции."""
        logger.info(
            "Запуск станционного узла АГЗС: режим=%s, порт=%s, адреса=%s, БД=%s, VPS=%s (sync=%s)",
            self.settings.source_mode,
            self.settings.serial_port,
            self.settings.pump_addresses,
            self.settings.db_path,
            self.settings.vps_base_url,
            self.settings.sync_enabled,
        )
        self._announce_vps()
        cycle = 0
        try:
            while max_cycles is None or cycle < max_cycles:
                cycle += 1
                closed = self.poll_cycle_once()
                self.maybe_sync_outbox(force=bool(closed))
                if max_cycles is None or cycle < max_cycles:
                    time.sleep(self.settings.poll_interval_sec)
        except KeyboardInterrupt:
            logger.info("Остановка станционного узла по сигналу оператора...")
        finally:
            self.link.close()
