"""Главный сервис станционного узла: цикл опроса АСКА-02, запись в SQLite и отправка на VPS."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone

from agzs_edge.config import EdgeSettings
from agzs_edge.iskra import (
    CMD_TEST_ASCII,
    STATE_COMPLETED,
    STATE_DOSE_SET,
    STATE_IDLE,
    STATE_STOPPED,
    IskraFrameError,
    IskraTelemetryFrame,
    build_reset_command,
    build_stop_command,
    parse_iskra_frame,
    verify_frame_checksum,
)
from agzs_edge.port_lock import ExclusivePortLock
from agzs_edge.psu_controller import PsuControlError, Uzsg01PsuController, send_buttons_param_to_pumps
from agzs_edge.serial_link import AskaLink, SerialAskaLink, build_link
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import OutboxSyncWorker, probe_vps_link
from agzs_edge.tracker import CompletedDispense, PumpDispenseTracker
from agzs_edge.updater import read_update_state, write_update_state

logger = logging.getLogger(__name__)


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
        initial_committed = self.db.get_recorded_stop_volumes()
        initial_prices = self.db.get_known_prices()
        self.tracker = PumpDispenseTracker(
            station_code=settings.station_code,
            pause_on_stopped=False,
            initial_committed_by_addr=initial_committed,
            initial_prices_by_addr=initial_prices,
        )
        self.sync_worker = sync_worker or OutboxSyncWorker(
            self.db,
            vps_base_url=settings.vps_base_url,
            device_token=settings.device_token,
            allow_insecure_http=settings.allow_insecure_http,
        )
        self._last_sync_ts = 0.0
        self._last_seen: dict[int, tuple[str, str, int, int]] = {}
        self._last_frame_by_addr: dict[int, IskraTelemetryFrame] = {}
        self._stop_07_since: dict[int, float] = {}
        self._stop_04_since: dict[int, float] = {}
        self._stop_requested: bool = False
        self._pumps_locked_for_update: bool = False
        self._restore_buttons_pending: bool = False
        self._buttons_restore_attempts: int = 0
        self._buttons_verify_pending: set[int] = set()
        self._operator_button_attempts: dict[int, int] = {}
        self._dispensing_seen: set[int] = set()
        self._last_counter_reconcile_ts: float = 0.0
        self._sync_wake_event = threading.Event()
        self._sync_stop_event = threading.Event()
        self._sync_thread: threading.Thread | None = None

    def request_stop(self) -> None:
        """Запрашивает мягкую остановку сервиса после завершения активных наливов."""
        self._stop_requested = True

    def is_idle_for_update(self) -> bool:
        """True, если нет активных наливов/пауз и нет отложенного авто-сброса 0x37."""
        return (
            not self.tracker.has_active_sessions()
            and not self._stop_07_since
            and not self._stop_04_since
        )

    def _tx_checksum_mode(self) -> str:
        return self.settings.layout.tx_checksum_mode

    def _can_control_buttons(self) -> bool:
        return (
            not self.settings.read_only
            and self.settings.lock_buttons_on_update
            and self.settings.source_mode != "emulator"
        )

    @staticmethod
    def _buttons_match_target_mode(frame: IskraTelemetryFrame | None, target_mode: str) -> bool:
        """Возвращает True, если в живом кадре биты 6 и 5 байта 17 уже соответствуют target_mode."""
        if frame is None or not frame.flags_raw.startswith("P"):
            return False
        if target_mode == "enable":
            return frame.start_stop_buttons_enabled and frame.reset_button_enabled
        if target_mode == "lock-reset":
            return frame.start_stop_buttons_enabled and not frame.reset_button_enabled
        return False

    def lock_pump_buttons_for_update(self) -> list[int]:
        """Отключает физические кнопки на колонках (команда 0x38, код 0.17) на время обновления ПО."""
        if not self._can_control_buttons():
            return []
        locked, errors = send_buttons_param_to_pumps(
            self.link,
            self.settings.pump_addresses,
            "0.17",
            checksum_mode=self._tx_checksum_mode(),
            last_frames=self._last_frame_by_addr,
        )
        for address, err in errors:
            logger.warning("Колонка #%d: ошибка блокировки кнопок (0.17): %s", address, err)
        for address in locked:
            logger.info("Колонка #%d: кнопки на ГРК заблокированы (0.17) на время обновления ПО", address)
        self._pumps_locked_for_update = True
        self._restore_buttons_pending = False
        self._buttons_restore_attempts = 0
        self._buttons_verify_pending.clear()
        if not errors:
            cur_state = read_update_state(self.settings)
            if cur_state is not None and cur_state.in_progress and not cur_state.buttons_locked:
                write_update_state(self.settings, replace(cur_state, buttons_locked=True))
        return locked

    def restore_pump_buttons(self) -> list[int]:
        """Включает физические кнопки на колонках командой 000016, без сброса 0x37."""
        if not self._can_control_buttons():
            return []

        if self._buttons_verify_pending and not self._pumps_locked_for_update:
            for addr in list(self._buttons_verify_pending):
                frame = self._last_frame_by_addr.get(addr)
                if frame is None or not frame.is_v310_status:
                    self._buttons_verify_pending.discard(addr)
                elif self._buttons_match_target_mode(frame, self.settings.pump_buttons_mode):
                    self._buttons_verify_pending.discard(addr)
            if not self._buttons_verify_pending and not self._restore_buttons_pending:
                self._buttons_restore_attempts = 0

        if self._pumps_locked_for_update:
            addresses_to_update = self.settings.pump_addresses
        elif self._restore_buttons_pending:
            addresses_to_update = tuple(
                addr
                for addr in self.settings.pump_addresses
                if not self._buttons_match_target_mode(
                    self._last_frame_by_addr.get(addr),
                    self.settings.pump_buttons_mode,
                )
            )
        elif self._buttons_verify_pending:
            addresses_to_update = tuple(
                addr for addr in self.settings.pump_addresses if addr in self._buttons_verify_pending
            )
        else:
            addresses_to_update = ()

        if not addresses_to_update:
            self._pumps_locked_for_update = False
            self._restore_buttons_pending = False
            self._buttons_restore_attempts = 0
            return []

        if self._buttons_restore_attempts >= 5 and not self._pumps_locked_for_update:
            logger.warning(
                "Кнопки на колонках %s не переключились за %d попыток (возможна прошивка УЗСГ-01 «только под ККМ»).",
                addresses_to_update,
                self._buttons_restore_attempts,
            )
            self._restore_buttons_pending = False
            self._buttons_verify_pending.clear()
            return []

        param_code = "0.16"
        restored, errors = send_buttons_param_to_pumps(
            self.link,
            addresses_to_update,
            param_code,
            checksum_mode=self._tx_checksum_mode(),
            last_frames=self._last_frame_by_addr,
            reset_after=False,
        )
        for address, err in errors:
            logger.warning("Колонка #%d: ошибка включения кнопок (%s): %s", address, param_code, err)
        for address in restored:
            logger.info("Колонка #%d: кнопки на ГРК включены (%s)", address, param_code)

        self._pumps_locked_for_update = False
        self._buttons_restore_attempts += 1
        if errors:
            self._restore_buttons_pending = self._buttons_restore_attempts < 5
            for addr in restored:
                self._buttons_verify_pending.add(addr)
        else:
            self._restore_buttons_pending = False
            for addr in restored:
                self._buttons_verify_pending.add(addr)
        return restored

    def _record_dispense_to_db(
        self,
        completed: CompletedDispense,
        *,
        mark_stop_vol: int | None = None,
    ) -> bool:
        dispenser_id = self.settings.dispenser_uuid(completed.pump_address)
        inserted = self.db.record_completed_dispense(
            completed,
            station_id=self.settings.station_id,
            dispenser_id=dispenser_id,
            tank_id=self.settings.tank_id or None,
            mark_stop_vol=mark_stop_vol,
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
            self._sync_wake_event.set()
        return inserted

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
                if self.settings.trace_frames:
                    logger.info(
                        "Кадр #%d TEST нет ответа hex_tx=%s",
                        address,
                        raw_res.request_bytes.hex(" ").upper(),
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

            if frame.address != address or frame.command_code != CMD_TEST_ASCII:
                logger.warning(
                    "Адрес %d: получен чужой/внеплановый кадр (#%d, cmd=0x%02X) — игнорируем",
                    address,
                    frame.address,
                    frame.command_code,
                )
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=raw_res.response_bytes,
                    valid=False,
                    note=(
                        f"несовпадение адреса/команды: ожидался #{address}/0x34, "
                        f"получен #{frame.address}/0x{frame.command_code:02X}"
                    ),
                )
                continue

            self._last_frame_by_addr[address] = frame
            self._trace_test_frame(frame)

            if self.settings.save_raw_frames or self.settings.trace_frames or frame.has_protocol_alarm:
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=raw_res.response_bytes,
                    valid=True,
                    note=f"state={frame.state_code} err={frame.error_code} ml={frame.effective_volume_ml}",
                )

            if not frame.is_parameter_readout:
                self.db.update_live_state(frame, observed_at=now)
                was_dispensing = address in self._dispensing_seen
                if frame.is_dispensing:
                    self._dispensing_seen.add(address)
                else:
                    self._dispensing_seen.discard(address)
            else:
                was_dispensing = False
            signature = (frame.state_code, frame.price_raw, frame.effective_volume_ml, frame.status_byte17)
            if self._last_seen.get(address) != signature:
                self._last_seen[address] = signature
                button_note = ""
                if frame.is_v310_status:
                    button_note = (
                        f", пуск/стоп={'вкл' if frame.start_stop_buttons_enabled else 'выкл'}"
                        f", сброс={'вкл' if frame.reset_button_enabled else 'выкл'}"
                    )
                if frame.completed_volume_ml is not None:
                    logger.info(
                        "Колонка #%d на связи: сост=%s(%s), итог налива=%d мл, цены в кадре нет%s",
                        address,
                        frame.state_code,
                        frame.state_name,
                        frame.completed_volume_ml,
                        button_note,
                    )
                else:
                    logger.info(
                        "Колонка #%d на связи: сост=%s(%s), цена=%.2f ₸/л, объём=%d мл%s",
                        address,
                        frame.state_code,
                        frame.state_name,
                        frame.price_kzt_per_liter,
                        frame.effective_volume_ml,
                        button_note,
                    )
            completed = self.tracker.process_frame(frame, observed_at=now)
            if (
                completed is None
                and not frame.is_parameter_readout
                and frame.state_code in {STATE_COMPLETED, STATE_STOPPED}
                and not frame.valve_open
            ):
                completed = self.tracker.recover_untracked_stop(frame, observed_at=now)
            if completed is not None:
                if self._record_dispense_to_db(completed, mark_stop_vol=frame.effective_volume_ml):
                    closed_dispenses.append(completed)

            self._maybe_stop_on_finish(address, frame, was_dispensing=was_dispensing)
            self._maybe_stop_on_dose_entry(address, frame, was_dispensing=was_dispensing)

            auto_closed = self._maybe_auto_reset(address, frame, completed=completed, observed_at=now)
            if auto_closed is not None:
                closed_dispenses.append(auto_closed)

        self._sync_pump_buttons_with_update_state()
        self._ensure_operator_buttons()
        self._maybe_reconcile_counters(observed_at=now)
        return closed_dispenses

    def _trace_test_frame(self, frame: IskraTelemetryFrame) -> None:
        """Пишет каждый ответ TEST: HEX, оба байта Status и Sost, поле, объём, BCC."""
        if not self.settings.trace_frames:
            return
        raw = frame.raw_bytes
        status = raw[17:19]
        sost = raw[19:21]
        bcc_ok = verify_frame_checksum(raw, self.settings.layout)
        dose_note = ""
        if frame.preset_dose_ml is not None:
            dose_note = f" доза_мл={frame.preset_dose_ml}"
        logger.info(
            "Кадр #%d TEST hex=%s status=%02X %02X sost=%02X %02X field=%s vol=%s bcc=%02X ok=%d клапан=%d сост=%s%s",
            frame.address,
            frame.raw_hex,
            status[0],
            status[1] if len(status) > 1 else 0,
            sost[0] if sost else 0,
            sost[1] if len(sost) > 1 else 0,
            frame.price_raw,
            frame.volume_raw,
            frame.checksum_byte,
            1 if bcc_ok else 0,
            1 if frame.valve_open else 0,
            frame.state_code,
            dose_note,
        )

    def _maybe_stop_on_finish(
        self,
        address: int,
        frame: IskraTelemetryFrame,
        *,
        was_dispensing: bool,
    ) -> None:
        """При выходе колонки из пуска ('03' -> '07'/'04') шлёт один ОСТАНОВ (0x36) для отключения насоса на АСКА-02."""
        if not was_dispensing or frame.state_code not in {STATE_COMPLETED, STATE_STOPPED}:
            return
        if self.settings.read_only or not self.settings.auto_stop_on_finish:
            return
        self._send_stop_command(
            address,
            reason=f"выход из пуска в '{frame.state_code}' для отключения насоса на АСКА-02",
        )

    def _maybe_stop_on_dose_entry(
        self,
        address: int,
        frame: IskraTelemetryFrame,
        *,
        was_dispensing: bool,
    ) -> None:
        """При переходе '03' -> '01' шлёт один ОСТАНОВ (0x36), чтобы прервать налив.

        Набор дозы в этом переходе начинается, пока БУН ещё может гудеть и объём
        ещё рос. Команда не ждёт остановки объёма и не зависит от автостопа на '07'.
        Повторный кадр '01' команду не дублирует: флаг пуска уже снят.
        """
        if not was_dispensing or frame.state_code != STATE_DOSE_SET:
            return
        if self.settings.read_only:
            return
        self._send_stop_command(
            address,
            reason="переход из пуска '03' в набор дозы '01', чтобы прервать налив и отключить БУН",
        )

    def _send_stop_command(self, address: int, *, reason: str) -> None:
        req = build_stop_command(address, checksum_mode=self._tx_checksum_mode())
        try:
            res = self.link.send_command(address, req)
        except Exception as exc:
            logger.warning("Колонка #%d: не удалось отправить ОСТАНОВ (0x36), %s: %s", address, reason, exc)
            return
        logger.info("Колонка #%d: %s — отправлен ОСТАНОВ (0x36)", address, reason)
        if res.error_message:
            logger.warning("Колонка #%d: ответ на ОСТАНОВ (0x36): %s", address, res.error_message)

    def _ensure_operator_buttons(self) -> None:
        """В готовности '05' шлёт 000016, если «ПУСК/СТОП» или «СБРОС» на корпусе выключены.

        000018 не используется: он блокирует «СБРОС». После 000016 команда 0x37 не уходит.
        При AGZS_READ_ONLY=1 или AGZS_TRACE_FRAMES=1 команда не отправляется.
        """
        if self.settings.read_only:
            return
        if self.settings.source_mode == "emulator":
            return
        if self.settings.trace_frames:
            return
        if self._can_control_buttons() or self._pumps_locked_for_update:
            return
        update_state = read_update_state(self.settings)
        if update_state is not None and update_state.in_progress:
            return
        if not self.is_idle_for_update():
            return

        pending: list[int] = []
        for address in self.settings.pump_addresses:
            frame = self._last_frame_by_addr.get(address)
            if frame is None or not frame.is_v310_status:
                continue
            if frame.state_code != STATE_IDLE or frame.valve_open or frame.is_dispensing:
                continue
            if frame.start_stop_buttons_enabled and frame.reset_button_enabled:
                self._operator_button_attempts.pop(address, None)
                continue
            if self._operator_button_attempts.get(address, 0) >= 5:
                continue
            pending.append(address)
        if not pending:
            return

        param_code = "0.16"
        restored, errors = send_buttons_param_to_pumps(
            self.link,
            tuple(pending),
            param_code,
            checksum_mode=self._tx_checksum_mode(),
            last_frames=self._last_frame_by_addr,
            reset_after=False,
        )
        failed = {address for address, _err in errors}
        for address, err in errors:
            attempt = self._operator_button_attempts.get(address, 0) + 1
            self._operator_button_attempts[address] = attempt
            logger.warning(
                "Колонка #%d: ошибка включения кнопок (%s), попытка %d: %s",
                address,
                param_code,
                attempt,
                err,
            )
            if attempt >= 5:
                logger.warning(
                    "Колонка #%d: кнопки не включились за 5 попыток (возможна прошивка «только под ККМ»).",
                    address,
                )
        for address in restored:
            if address in failed:
                continue
            attempt = self._operator_button_attempts.get(address, 0) + 1
            self._operator_button_attempts[address] = attempt
            logger.info("Колонка #%d: отправлено включение кнопок (%s)", address, param_code)

    def _sync_pump_buttons_with_update_state(self) -> None:
        if not self._can_control_buttons():
            return
        update_state = read_update_state(self.settings)
        if update_state is not None and update_state.in_progress:
            if self.is_idle_for_update() and not self._pumps_locked_for_update:
                self.lock_pump_buttons_for_update()
                self._restore_buttons_pending = False
        elif (
            self._pumps_locked_for_update
            or (self._restore_buttons_pending and self.is_idle_for_update())
            or (self._buttons_verify_pending and self.is_idle_for_update())
        ):
            self.restore_pump_buttons()

    def _send_auto_reset_command(self, address: int, *, observed_at: datetime, reason: str) -> None:
        req = build_reset_command(address, checksum_mode=self._tx_checksum_mode())
        res = self.link.send_command(address, req)
        logger.info("Колонка #%d: отправлен автоматический СБРОС (0x37) (%s)", address, reason)
        if res.has_response:
            try:
                reset_frame = parse_iskra_frame(res.response_bytes, self.settings.layout)
                if reset_frame.address == address:
                    self.db.update_live_state(reset_frame, observed_at=observed_at)
                    self._last_frame_by_addr[address] = reset_frame
                    self._last_seen[address] = (
                        reset_frame.state_code,
                        reset_frame.price_raw,
                        reset_frame.effective_volume_ml,
                        reset_frame.status_byte17,
                    )
                    if reset_frame.state_code == STATE_IDLE:
                        self.tracker.mark_reset(address)
                else:
                    logger.warning(
                        "Колонка #%d: ответ на автосброс пришёл от #%d — игнорируем",
                        address,
                        reset_frame.address,
                    )
            except IskraFrameError as exc:
                logger.warning("Колонка #%d: некорректный ответ на автосброс (%s)", address, exc)
        elif res.error_message:
            logger.warning("Колонка #%d: ошибка при автосбросе (%s)", address, res.error_message)

    def _close_paused_04(
        self,
        address: int,
        frame: IskraTelemetryFrame,
        *,
        observed_at: datetime,
        send_reset: bool,
        reason: str,
    ) -> CompletedDispense | None:
        self._stop_04_since.pop(address, None)
        paused_done = self.tracker.finish_paused_session(address, observed_at=observed_at)
        if paused_done is None:
            paused_done = self.tracker.recover_untracked_stop(frame, observed_at=observed_at)
        recorded_closed: CompletedDispense | None = None
        if paused_done is not None:
            if self._record_dispense_to_db(paused_done, mark_stop_vol=frame.effective_volume_ml):
                recorded_closed = paused_done
        if send_reset:
            self._send_auto_reset_command(address, observed_at=observed_at, reason=reason)
        return recorded_closed

    def _maybe_auto_reset(
        self,
        address: int,
        frame: IskraTelemetryFrame,
        *,
        completed: CompletedDispense | None,
        observed_at: datetime,
    ) -> CompletedDispense | None:
        del completed
        if frame.address != address or frame.valve_open:
            self._stop_07_since.pop(address, None)
            self._stop_04_since.pop(address, None)
            return None

        if frame.state_code == STATE_COMPLETED:
            self._stop_04_since.pop(address, None)
            if self.settings.read_only or not self.settings.auto_reset_on_stop:
                self._stop_07_since.pop(address, None)
                return None

            now_mono = time.monotonic()
            if self.settings.auto_reset_delay_sec <= 0 or self._stop_requested:
                should_reset = True
            else:
                first_seen = self._stop_07_since.setdefault(address, now_mono)
                should_reset = (now_mono - first_seen) >= self.settings.auto_reset_delay_sec

            if not should_reset:
                return None

            self._stop_07_since.pop(address, None)
            self._send_auto_reset_command(
                address,
                observed_at=observed_at,
                reason="снятие блокировки после останова 07",
            )
            return None

        if frame.state_code == STATE_STOPPED:
            self._stop_07_since.pop(address, None)
            if self._stop_requested:
                can_reset = (
                    not self.settings.read_only
                    and self.settings.auto_reset_on_stop
                    and self.settings.auto_reset_stopped_delay_sec > 0
                )
                return self._close_paused_04(
                    address,
                    frame,
                    observed_at=observed_at,
                    send_reset=can_reset,
                    reason="остановка службы при паузе 04",
                )

            if (
                self.settings.read_only
                or not self.settings.auto_reset_on_stop
                or self.settings.auto_reset_stopped_delay_sec <= 0
            ):
                self._stop_04_since.pop(address, None)
                return None

            now_mono = time.monotonic()
            first_seen = self._stop_04_since.setdefault(address, now_mono)
            if (now_mono - first_seen) < self.settings.auto_reset_stopped_delay_sec:
                return None

            return self._close_paused_04(
                address,
                frame,
                observed_at=observed_at,
                send_reset=True,
                reason="таймаут паузы 04",
            )

        self._stop_07_since.pop(address, None)
        self._stop_04_since.pop(address, None)
        return None

    def _maybe_reconcile_counters(self, *, observed_at: datetime) -> None:
        if self.settings.read_only or self.settings.counter_reconcile_interval_sec <= 0:
            return
        if not self.is_idle_for_update():
            return
        now_mono = time.monotonic()
        if (
            self._last_counter_reconcile_ts > 0
            and (now_mono - self._last_counter_reconcile_ts) < self.settings.counter_reconcile_interval_sec
        ):
            return
        for addr in self.settings.pump_addresses:
            frame = self._last_frame_by_addr.get(addr)
            if frame is None or frame.state_code != STATE_IDLE:
                return

        self._last_counter_reconcile_ts = now_mono
        ctrl = Uzsg01PsuController(self.link, layout=self.settings.layout)
        for addr in self.settings.pump_addresses:
            try:
                total_liters = ctrl.read_total_counter_1(addr)
                if total_liters is not None:
                    delta, discrepancy = self.db.record_counter_audit(
                        addr,
                        total_liters,
                        observed_at=observed_at,
                    )
                    if discrepancy is not None and abs(discrepancy) > 0.5:
                        logger.warning(
                            "Колонка #%d: расхождение суммарного счётчика (0.11) с БД: Δсч=%.3f л, расхождение=%.3f л",
                            addr,
                            delta or 0.0,
                            discrepancy,
                        )
            except (PsuControlError, Exception) as exc:
                logger.warning("Колонка #%d: ошибка сверки суммарного счётчика (0.11): %s", addr, exc)

    def _announce_vps(self) -> None:
        """Один раз при старте проверяет, что центральный сервер узнаёт токен станции."""
        if not self.settings.sync_enabled:
            logger.info("Отправка на центральный сервер выключена")
            return
        result = probe_vps_link(
            self.settings.vps_base_url,
            self.settings.device_token,
            self.settings.tank_id,
            allow_insecure_http=self.settings.allow_insecure_http,
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

    def _start_sync_thread(self) -> None:
        if not self.settings.sync_enabled:
            logger.info("Отправка на центральный сервер выключена")
            return
        requeued = self.db.requeue_auth_blocked()
        if requeued > 0:
            logger.info("Возвращено в очередь %d ранее заблокированных (401/403) записей outbox", requeued)
        self._sync_stop_event.clear()
        self._sync_wake_event.clear()

        def _sync_loop() -> None:
            self._announce_vps()
            wait_sec = max(0.1, self.settings.sync_interval_sec) if self.settings.sync_interval_sec > 0 else 0.1
            while not self._sync_stop_event.is_set():
                self._sync_wake_event.wait(timeout=wait_sec)
                self._sync_wake_event.clear()
                if self._sync_stop_event.is_set():
                    break
                try:
                    self.sync_worker.flush_due()
                except Exception as exc:
                    logger.warning("Ошибка фоновой синхронизации с VPS: %s", exc)
            try:
                self.sync_worker.flush_due()
            except Exception as exc:
                logger.warning("Ошибка финальной синхронизации с VPS: %s", exc)

        self._sync_thread = threading.Thread(
            target=_sync_loop,
            name="agzs-vps-sync",
            daemon=True,
        )
        self._sync_thread.start()

    def _stop_sync_thread(self) -> None:
        thread = self._sync_thread
        if thread is None:
            return
        self._sync_stop_event.set()
        self._sync_wake_event.set()
        thread.join(timeout=15.0)
        self._sync_thread = None

    def serve(
        self,
        *,
        max_cycles: int | None = None,
        graceful_timeout_sec: float = 120.0,
    ) -> None:
        """Непрерывный цикл работы на станции с мягким завершением при остановке."""
        # Опрос не шлёт «Пуск» (0x35). В режиме только чтения команда остаётся выключенной.
        computer_sends_start = False
        port_lock: ExclusivePortLock | None = None
        if self.settings.source_mode != "emulator" and isinstance(self.link, SerialAskaLink):
            port_lock = ExclusivePortLock(
                self.settings.serial_port, lock_dir=self.settings.db_path.parent
            )
            port_lock.acquire()
        logger.info(
            "Запуск станционного узла АГЗС: режим=%s, порт=%s, адреса=%s, БД=%s, VPS=%s (sync=%s), "
            "пуск 0x35=%s, стоп 0x36 при 07=%s, стоп 0x36 при 03→01=%s, сброс 07=%s через %.0f с, пауза 04=%s, кнопки=%s, кадры=%s",
            self.settings.source_mode,
            self.settings.serial_port,
            self.settings.pump_addresses,
            self.settings.db_path,
            self.settings.vps_base_url,
            self.settings.sync_enabled,
            computer_sends_start,
            self.settings.auto_stop_on_finish,
            not self.settings.read_only,
            self.settings.auto_reset_on_stop,
            self.settings.auto_reset_delay_sec,
            "выкл" if self.settings.auto_reset_stopped_delay_sec <= 0 else f"{self.settings.auto_reset_stopped_delay_sec:.0f} с",
            self.settings.pump_buttons_mode,
            "все" if self.settings.trace_frames else "смена",
        )
        self._start_sync_thread()
        if self._can_control_buttons():
            initial_update = read_update_state(self.settings)
            if initial_update is None or not initial_update.in_progress:
                self._restore_buttons_pending = True

        previous_handlers: dict[int, object] = {}
        is_main_thread = threading.current_thread() is threading.main_thread()
        if is_main_thread:
            def _handle_stop_signal(signum: int, _frame: object) -> None:
                if not self._stop_requested:
                    self.request_stop()
                    active = self.tracker.active_addresses()
                    if active:
                        logger.info(
                            "Получен сигнал остановки (%s): ожидаем завершения активного налива на колонках %s...",
                            signum,
                            active,
                        )
                    else:
                        logger.info(
                            "Получен сигнал остановки (%s): завершаем текущий цикл и синхронизируем outbox...",
                            signum,
                        )
                    return
                if signum == signal.SIGINT:
                    raise KeyboardInterrupt

            sig_candidates: list[int] = [signal.SIGINT]
            sigterm = getattr(signal, "SIGTERM", None)
            if isinstance(sigterm, int):
                sig_candidates.append(sigterm)
            for sig in sig_candidates:
                try:
                    previous_handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, _handle_stop_signal)
                except (ValueError, OSError):
                    pass

        cycle = 0
        stop_deadline: float | None = None
        try:
            while max_cycles is None or cycle < max_cycles:
                cycle += 1
                closed = self.poll_cycle_once()
                if closed and self.settings.sync_enabled:
                    self._sync_wake_event.set()

                if self._stop_requested:
                    if stop_deadline is None:
                        stop_deadline = time.monotonic() + max(0.0, graceful_timeout_sec)
                    if self.is_idle_for_update():
                        update_state = read_update_state(self.settings)
                        if (
                            update_state is not None
                            and update_state.in_progress
                            and not self._pumps_locked_for_update
                        ):
                            self.lock_pump_buttons_for_update()
                        logger.info("Станционный узел безопасно остановлен: все наливы завершены.")
                        break
                    if time.monotonic() >= stop_deadline:
                        logger.warning(
                            "Таймаут мягкой остановки (%.1f с), активные колонки=%s — принудительный выход.",
                            graceful_timeout_sec,
                            self.tracker.active_addresses(),
                        )
                        break

                if max_cycles is None or cycle < max_cycles:
                    time.sleep(self.settings.poll_interval_sec)
        except KeyboardInterrupt:
            logger.info("Остановка станционного узла по сигналу оператора...")
        finally:
            self._stop_sync_thread()
            if is_main_thread:
                for sig, prev in previous_handlers.items():
                    try:
                        signal.signal(sig, prev)  # type: ignore[arg-type]
                    except (ValueError, OSError):
                        pass
            self.link.close()
            if port_lock is not None:
                port_lock.release()
