"""Главный сервис станционного узла: цикл опроса АСКА-02, запись в SQLite и отправка на VPS."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import IskraFrameError, parse_iskra_frame
from agzs_edge.serial_link import AskaLink, EmulatorAskaLink, SerialAskaLink
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker
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

    def poll_cycle_once(self, *, observed_at: datetime | None = None) -> list[CompletedDispense]:
        """Опрашивает все адреса из `settings.pump_addresses` по одному разу (команда «Тест»)."""
        closed_dispenses: list[CompletedDispense] = []
        now = observed_at or datetime.now(timezone.utc)

        for address in self.settings.pump_addresses:
            raw_res = self.link.poll_test(address)
            if not raw_res.has_response:
                if self.settings.save_raw_frames:
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

        return closed_dispenses

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
