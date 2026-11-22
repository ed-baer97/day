"""Трекер состояния колонки УЗГС-01 и расчёт налитого объёма (dispensed_ml).

Правила расчёта объёма по ТЗ:
1. Обычная доза ('dose'):
   Поле объёма в кадре — остаток дозы, оно уменьшается по мере налива.
   Отпущено = задали минус осталось (`dispensed_ml = preset_ml - current_ml`).
   Пример: задали 20 000 мл, в кадре 12 500 -> налито 7 500 мл.
2. «До полного» ('full_tank'):
   Дозы заранее нет, колонка останавливается по ослаблению струи или по кнопке.
   То же поле объёма в кадре уже содержит отпущенные миллилитры (`dispensed_ml = current_ml`),
   оно увеличивается по мере налива.
3. В базу уход пишется как `dispensed_ml` по закрытой заправке.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agzs_edge.iskra import (
    STATE_COMPLETED,
    STATE_DISPENSING,
    STATE_DOSE_SET,
    STATE_ERROR,
    STATE_IDLE,
    STATE_STOPPED,
    IskraTelemetryFrame,
)

MODE_UNKNOWN = "unknown"
MODE_DOSE = "dose"
MODE_FULL_TANK = "full_tank"


@dataclass(frozen=True)
class CompletedDispense:
    """Закрытая заправка, готовая к записи в локальную БД и отправке на VPS."""

    external_txn_id: str
    pump_address: int
    mode: str  # 'dose' | 'full_tank'
    preset_ml: int | None
    dispensed_ml: int
    volume_liters: float
    price_kzt_per_liter: float
    final_state_code: str
    error_code: str
    started_at: datetime
    finished_at: datetime
    last_raw_frame_hex: str


def _frame_error_code(frame: IskraTelemetryFrame) -> str:
    if frame.error_code != "00":
        return frame.error_code
    if frame.column_error_code > 0:
        return f"{frame.column_error_code:02d}"
    return "00"


@dataclass
class _ActiveSession:
    pump_address: int
    started_at: datetime
    initial_volume_ml: int
    preset_ml: int | None
    mode: str = MODE_UNKNOWN
    current_dispensed_ml: int = 0
    last_volume_ml: int = 0
    price_kzt_per_liter: float = 0.0
    last_state_code: str = STATE_DISPENSING
    last_error_code: str = "00"
    last_raw_frame_hex: str = ""
    paused_at: datetime | None = None
    is_mass_mode: bool = False
    volume_counts_up: bool = False


class PumpDispenseTracker:
    """Отслеживает смену кадров «Тест» по каждой колонке (адреса 1..8) и закрывает наливы."""

    def __init__(
        self,
        station_code: str = "AGZS",
        *,
        pause_on_stopped: bool = False,
        initial_committed_by_addr: dict[int, int] | None = None,
        initial_prices_by_addr: dict[int, float] | None = None,
    ) -> None:
        self._station_code = station_code.strip() or "AGZS"
        self._pause_on_stopped = pause_on_stopped
        # Предварительно набранная доза на пульте (в состоянии DOSE_SET или IDLE с ненулевым заданием)
        self._staged_preset_ml: dict[int, int] = {}
        self._last_price_by_addr: dict[int, float] = {
            int(addr): float(price)
            for addr, price in (initial_prices_by_addr or {}).items()
            if price > 0
        }
        self._committed_since_reset: dict[int, int] = dict(initial_committed_by_addr or {})
        self._active: dict[int, _ActiveSession] = {}
        self._seq_counter: dict[int, int] = {}

    def active_session(self, address: int) -> _ActiveSession | None:
        return self._active.get(address)

    def has_active_sessions(self) -> bool:
        """Возвращает True, если хотя бы на одной колонке сейчас идёт налив или пауза '04'."""
        return bool(self._active)

    def has_paused_sessions(self) -> bool:
        """Возвращает True, если хотя бы одна колонка стоит на паузе '04' с открытой сессией."""
        return any(sess.paused_at is not None for sess in self._active.values())

    def active_addresses(self) -> tuple[int, ...]:
        """Возвращает отсортированный кортеж адресов колонок с активным наливом."""
        return tuple(sorted(self._active.keys()))

    def mark_reset(self, address: int) -> None:
        """Очищает учётный порог после успешного сброса колонки в '05'."""
        self._committed_since_reset.pop(address, None)

    def process_frame(
        self,
        frame: IskraTelemetryFrame,
        *,
        observed_at: datetime | None = None,
    ) -> CompletedDispense | None:
        """Обрабатывает очередной кадр «Тест» и возвращает CompletedDispense в момент закрытия заправки."""
        if frame.is_parameter_readout:
            return None
        now = observed_at or datetime.now(timezone.utc)
        addr = frame.address
        if frame.price_kzt_per_liter > 0:
            self._last_price_by_addr[addr] = frame.price_kzt_per_liter
        session = self._active.get(addr)

        if session is None:
            self._handle_idle_frame(frame, now)
            return None

        self._update_session_volume(session, frame)
        if frame.is_dispensing:
            session.paused_at = None
            return None

        if frame.state_code == STATE_STOPPED and self._pause_on_stopped:
            self._finalize_volume_on_stop(session, frame)
            if session.paused_at is None:
                session.paused_at = now
            return None

        return self._finish_session(addr, frame, now)

    def finish_paused_session(
        self,
        address: int,
        *,
        observed_at: datetime | None = None,
    ) -> CompletedDispense | None:
        """Принудительно закрывает заправку, стоящую на паузе '04', по истечении таймаута простоя."""
        session = self._active.get(address)
        if session is None or session.paused_at is None:
            return None
        finished_session = self._active.pop(address)
        self._staged_preset_ml.pop(address, None)

        counts_up = finished_session.volume_counts_up or finished_session.mode == MODE_FULL_TANK
        already = self._committed_since_reset.get(address, 0) if counts_up else 0
        dispensed_ml = finished_session.current_dispensed_ml - already
        if dispensed_ml <= 0:
            return None

        if counts_up:
            self._committed_since_reset[address] = finished_session.current_dispensed_ml

        now = observed_at or datetime.now(timezone.utc)
        final_mode = finished_session.mode if finished_session.mode != MODE_UNKNOWN else MODE_FULL_TANK
        seq = self._seq_counter.get(address, 0) + 1
        self._seq_counter[address] = seq
        started_epoch_ms = int(finished_session.started_at.timestamp() * 1000)
        txn_id = f"aska02-{self._station_code.lower()}-p{address}-{started_epoch_ms}-{seq}"

        return CompletedDispense(
            external_txn_id=txn_id,
            pump_address=address,
            mode=final_mode,
            preset_ml=finished_session.preset_ml if final_mode == MODE_DOSE else None,
            dispensed_ml=dispensed_ml,
            volume_liters=round(dispensed_ml / 1000.0, 3),
            price_kzt_per_liter=finished_session.price_kzt_per_liter,
            final_state_code=finished_session.last_state_code,
            error_code=finished_session.last_error_code,
            started_at=finished_session.started_at,
            finished_at=now,
            last_raw_frame_hex=finished_session.last_raw_frame_hex,
        )

    def recover_untracked_stop(
        self,
        frame: IskraTelemetryFrame,
        *,
        observed_at: datetime | None = None,
    ) -> CompletedDispense | None:
        """Восстанавливает заправку, если её активная фаза '03' была пропущена (или был рестарт ПК)."""
        addr = frame.address
        if self._active.get(addr) is not None:
            return None
        if frame.state_code not in {STATE_COMPLETED, STATE_STOPPED}:
            return None

        effective_vol = frame.effective_volume_ml
        already = self._committed_since_reset.get(addr, 0)
        delta_ml = effective_vol - already
        if delta_ml <= 0:
            return None

        self._committed_since_reset[addr] = effective_vol
        now = observed_at or datetime.now(timezone.utc)
        if frame.price_kzt_per_liter > 0:
            self._last_price_by_addr[addr] = frame.price_kzt_per_liter
        price = (
            frame.price_kzt_per_liter
            if frame.price_kzt_per_liter > 0
            else self._last_price_by_addr.get(addr, 0.0)
        )
        seq = self._seq_counter.get(addr, 0) + 1
        self._seq_counter[addr] = seq
        started_epoch_ms = int(now.timestamp() * 1000)
        txn_id = f"aska02-{self._station_code.lower()}-p{addr}-{started_epoch_ms}-{seq}"

        return CompletedDispense(
            external_txn_id=txn_id,
            pump_address=addr,
            mode="recovered_stop",
            preset_ml=None,
            dispensed_ml=delta_ml,
            volume_liters=round(delta_ml / 1000.0, 3),
            price_kzt_per_liter=price,
            final_state_code=frame.state_code,
            error_code=_frame_error_code(frame),
            started_at=now,
            finished_at=now,
            last_raw_frame_hex=frame.raw_hex,
        )

    def _handle_idle_frame(self, frame: IskraTelemetryFrame, now: datetime) -> None:
        addr = frame.address
        effective_vol = frame.effective_volume_ml
        if frame.state_code == STATE_IDLE:
            self._staged_preset_ml.pop(addr, None)
            self._committed_since_reset.pop(addr, None)
            return
        if frame.state_code == STATE_DOSE_SET:
            # На пульте УЗГС-01 набрали дозу перед пуском (например, 20 000 мл)
            if frame.is_v310_status:
                if frame.preset_dose_ml is not None and 0 < frame.preset_dose_ml < 900_000:
                    self._staged_preset_ml[addr] = frame.preset_dose_ml
            elif effective_vol > 0:
                self._staged_preset_ml[addr] = effective_vol
            return
        if frame.state_code in {STATE_ERROR, STATE_COMPLETED, STATE_STOPPED}:
            self._staged_preset_ml.pop(addr, None)
            return
        if not frame.is_dispensing:
            return

        if effective_vol < self._committed_since_reset.get(addr, 0):
            self._committed_since_reset.pop(addr, None)

        mode, preset_ml, dispensed_ml, volume_counts_up = self._detect_initial_mode(addr, frame)
        self._active[addr] = _ActiveSession(
            pump_address=addr,
            started_at=now,
            initial_volume_ml=effective_vol,
            preset_ml=preset_ml,
            mode=mode,
            current_dispensed_ml=dispensed_ml,
            last_volume_ml=effective_vol,
            price_kzt_per_liter=(
                frame.price_kzt_per_liter
                if frame.price_kzt_per_liter > 0
                else self._last_price_by_addr.get(addr, 0.0)
            ),
            last_state_code=frame.state_code,
            last_error_code=_frame_error_code(frame),
            last_raw_frame_hex=frame.raw_hex,
            is_mass_mode=frame.is_mass_mode,
            volume_counts_up=volume_counts_up,
        )

    def _detect_initial_mode(self, addr: int, frame: IskraTelemetryFrame) -> tuple[str, int | None, int, bool]:
        staged_preset = self._staged_preset_ml.pop(addr, None)
        effective_vol = frame.effective_volume_ml
        if frame.flags_raw.startswith("P"):
            v310_preset: int | None = None
            if (
                frame.dose_type_bits in {0x11, 0x14}
                and frame.preset_dose_ml is not None
                and 0 < frame.preset_dose_ml < 900_000
            ):
                v310_preset = frame.preset_dose_ml
            elif staged_preset is not None and 0 < staged_preset < 900_000:
                v310_preset = staged_preset
            if v310_preset is not None:
                return MODE_DOSE, v310_preset, effective_vol, True
            return MODE_FULL_TANK, None, effective_vol, True
        if staged_preset is not None and staged_preset > 0 and effective_vol <= staged_preset:
            return MODE_DOSE, staged_preset, max(0, staged_preset - effective_vol), False
        if frame.flags_raw == "01":
            return MODE_DOSE, effective_vol, 0, False
        if frame.flags_raw == "02":
            return MODE_FULL_TANK, None, effective_vol, True
        if effective_vol == 0:
            return MODE_FULL_TANK, None, 0, True
        # Первое наблюдение налива с ненулевым числом (без кадра DOSE_SET):
        # точный режим выяснится на следующем шаге по направлению изменения числа.
        return MODE_UNKNOWN, effective_vol, 0, False

    def _finish_session(
        self,
        addr: int,
        frame: IskraTelemetryFrame,
        now: datetime,
    ) -> CompletedDispense | None:
        finished_session = self._active.pop(addr)
        self._staged_preset_ml.pop(addr, None)
        effective_vol = frame.effective_volume_ml

        # Учитываем финальный остаток при COMPLETED/STOPPED/ERROR, не затирая сбросом в 0 при IDLE
        if frame.state_code in {STATE_COMPLETED, STATE_STOPPED, STATE_ERROR}:
            self._finalize_volume_on_stop(finished_session, frame)
        elif (
            frame.state_code == STATE_IDLE
            and finished_session.paused_at is None
            and finished_session.mode == MODE_DOSE
            and not finished_session.volume_counts_up
            and effective_vol == 0
            and finished_session.preset_ml is not None
        ):
            finished_session.current_dispensed_ml = max(
                finished_session.current_dispensed_ml,
                finished_session.preset_ml,
            )

        final_mode = finished_session.mode if finished_session.mode != MODE_UNKNOWN else MODE_FULL_TANK
        counts_up = finished_session.volume_counts_up or final_mode == MODE_FULL_TANK
        if counts_up:
            already = self._committed_since_reset.get(addr, 0)
            dispensed_ml = finished_session.current_dispensed_ml - already
        else:
            dispensed_ml = finished_session.current_dispensed_ml

        if frame.state_code == STATE_IDLE:
            self._committed_since_reset.pop(addr, None)
        elif dispensed_ml > 0 and counts_up:
            self._committed_since_reset[addr] = finished_session.current_dispensed_ml

        if dispensed_ml <= 0:
            return None

        seq = self._seq_counter.get(addr, 0) + 1
        self._seq_counter[addr] = seq
        started_epoch_ms = int(finished_session.started_at.timestamp() * 1000)
        txn_id = f"aska02-{self._station_code.lower()}-p{addr}-{started_epoch_ms}-{seq}"

        final_err = _frame_error_code(frame)
        return CompletedDispense(
            external_txn_id=txn_id,
            pump_address=addr,
            mode=final_mode,
            preset_ml=finished_session.preset_ml if final_mode == MODE_DOSE else None,
            dispensed_ml=dispensed_ml,
            volume_liters=round(dispensed_ml / 1000.0, 3),
            price_kzt_per_liter=finished_session.price_kzt_per_liter,
            final_state_code=frame.state_code,
            error_code=final_err if final_err != "00" else finished_session.last_error_code,
            started_at=finished_session.started_at,
            finished_at=now,
            last_raw_frame_hex=frame.raw_hex,
        )

    def _update_session_volume(self, session: _ActiveSession, frame: IskraTelemetryFrame) -> None:
        if frame.price_kzt_per_liter > 0:
            session.price_kzt_per_liter = frame.price_kzt_per_liter
        session.last_state_code = frame.state_code
        err_code = _frame_error_code(frame)
        if err_code != "00":
            session.last_error_code = err_code
        session.last_raw_frame_hex = frame.raw_hex
        if frame.is_mass_mode:
            session.is_mass_mode = True

        if not frame.is_dispensing:
            return

        curr = frame.effective_volume_ml
        if session.volume_counts_up and session.mode == MODE_DOSE and frame.preset_dose_ml and 0 < frame.preset_dose_ml < 900_000:
            session.preset_ml = frame.preset_dose_ml
        if session.mode == MODE_UNKNOWN:
            self._resolve_unknown_mode(session, curr)

        if session.volume_counts_up or session.mode == MODE_FULL_TANK:
            session.current_dispensed_ml = max(session.current_dispensed_ml, curr)
        elif session.mode == MODE_DOSE:
            preset = session.preset_ml or session.initial_volume_ml
            if curr <= preset:
                session.current_dispensed_ml = max(session.current_dispensed_ml, preset - curr)

        session.last_volume_ml = curr

    @staticmethod
    def _resolve_unknown_mode(session: _ActiveSession, curr: int) -> None:
        if curr < session.initial_volume_ml:
            session.mode = MODE_DOSE
            session.preset_ml = session.initial_volume_ml
            session.volume_counts_up = False
        elif curr > session.initial_volume_ml:
            session.mode = MODE_FULL_TANK
            session.preset_ml = None
            session.volume_counts_up = True

    def _finalize_volume_on_stop(self, session: _ActiveSession, frame: IskraTelemetryFrame) -> None:
        if frame.completed_volume_ml is not None:
            session.current_dispensed_ml = frame.completed_volume_ml
            return
        curr = frame.effective_volume_ml
        if session.mode == MODE_UNKNOWN:
            if curr < session.initial_volume_ml:
                session.mode = MODE_DOSE
                session.preset_ml = session.initial_volume_ml
                session.volume_counts_up = False
            elif curr > 0:
                session.mode = MODE_FULL_TANK
                session.preset_ml = None
                session.volume_counts_up = True

        if session.volume_counts_up or session.mode == MODE_FULL_TANK:
            if curr > session.current_dispensed_ml:
                session.current_dispensed_ml = curr
        elif session.mode == MODE_DOSE:
            preset = session.preset_ml or session.initial_volume_ml
            if 0 <= curr <= preset:
                dispensed = preset - curr
                if dispensed > session.current_dispensed_ml:
                    session.current_dispensed_ml = dispensed
