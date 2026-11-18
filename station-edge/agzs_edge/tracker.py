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


class PumpDispenseTracker:
    """Отслеживает смену кадров «Тест» по каждой колонке (адреса 1..6) и закрывает наливы."""

    def __init__(self, station_code: str = "AGZS") -> None:
        self._station_code = station_code.strip() or "AGZS"
        # Предварительно набранная доза на пульте (в состоянии DOSE_SET или IDLE с ненулевым заданием)
        self._staged_preset_ml: dict[int, int] = {}
        self._last_price_by_addr: dict[int, float] = {}
        self._active: dict[int, _ActiveSession] = {}
        self._seq_counter: dict[int, int] = {}

    def active_session(self, address: int) -> _ActiveSession | None:
        return self._active.get(address)

    def process_frame(
        self,
        frame: IskraTelemetryFrame,
        *,
        observed_at: datetime | None = None,
    ) -> CompletedDispense | None:
        """Обрабатывает очередной кадр «Тест» и возвращает CompletedDispense в момент закрытия заправки."""
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
            return None

        return self._finish_session(addr, frame, now)

    def _handle_idle_frame(self, frame: IskraTelemetryFrame, now: datetime) -> None:
        addr = frame.address
        if frame.state_code == STATE_DOSE_SET and frame.volume_ml > 0:
            # На пульте УЗГС-01 набрали дозу перед пуском (например, 20 000 мл)
            self._staged_preset_ml[addr] = frame.volume_ml
            return
        if frame.state_code in {STATE_IDLE, STATE_ERROR, STATE_COMPLETED, STATE_STOPPED}:
            self._staged_preset_ml.pop(addr, None)
            return
        if not frame.is_dispensing:
            return

        mode, preset_ml, dispensed_ml = self._detect_initial_mode(addr, frame)
        self._active[addr] = _ActiveSession(
            pump_address=addr,
            started_at=now,
            initial_volume_ml=frame.volume_ml,
            preset_ml=preset_ml,
            mode=mode,
            current_dispensed_ml=dispensed_ml,
            last_volume_ml=frame.volume_ml,
            price_kzt_per_liter=(
                frame.price_kzt_per_liter
                if frame.price_kzt_per_liter > 0
                else self._last_price_by_addr.get(addr, 0.0)
            ),
            last_state_code=frame.state_code,
            last_error_code=_frame_error_code(frame),
            last_raw_frame_hex=frame.raw_hex,
        )

    def _detect_initial_mode(self, addr: int, frame: IskraTelemetryFrame) -> tuple[str, int | None, int]:
        staged_preset = self._staged_preset_ml.pop(addr, None)
        if staged_preset is not None and staged_preset > 0 and frame.volume_ml <= staged_preset:
            return MODE_DOSE, staged_preset, max(0, staged_preset - frame.volume_ml)
        if frame.flags_raw.startswith("P"):
            return MODE_FULL_TANK, None, frame.volume_ml
        if frame.flags_raw == "01":
            return MODE_DOSE, frame.volume_ml, 0
        if frame.flags_raw == "02":
            return MODE_FULL_TANK, None, frame.volume_ml
        if frame.volume_ml == 0:
            return MODE_FULL_TANK, None, 0
        # Первое наблюдение налива с ненулевым числом (без кадра DOSE_SET):
        # точный режим выяснится на следующем шаге по направлению изменения числа.
        return MODE_UNKNOWN, frame.volume_ml, 0

    def _finish_session(
        self,
        addr: int,
        frame: IskraTelemetryFrame,
        now: datetime,
    ) -> CompletedDispense | None:
        finished_session = self._active.pop(addr)
        self._staged_preset_ml.pop(addr, None)

        # Учитываем финальный остаток при COMPLETED/STOPPED/ERROR, не затирая сбросом в 0 при IDLE
        if frame.state_code in {STATE_COMPLETED, STATE_STOPPED, STATE_ERROR}:
            self._finalize_volume_on_stop(finished_session, frame)
        elif (
            frame.state_code == STATE_IDLE
            and finished_session.mode == MODE_DOSE
            and frame.volume_ml == 0
            and finished_session.preset_ml is not None
        ):
            finished_session.current_dispensed_ml = max(
                finished_session.current_dispensed_ml,
                finished_session.preset_ml,
            )

        if finished_session.current_dispensed_ml <= 0:
            return None

        final_mode = finished_session.mode if finished_session.mode != MODE_UNKNOWN else MODE_FULL_TANK
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
            dispensed_ml=finished_session.current_dispensed_ml,
            volume_liters=round(finished_session.current_dispensed_ml / 1000.0, 3),
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

        if not frame.is_dispensing:
            return

        curr = frame.volume_ml
        if session.mode == MODE_UNKNOWN:
            self._resolve_unknown_mode(session, curr)

        if session.mode == MODE_DOSE:
            preset = session.preset_ml or session.initial_volume_ml
            if curr <= preset:
                session.current_dispensed_ml = max(session.current_dispensed_ml, preset - curr)
        elif session.mode == MODE_FULL_TANK:
            session.current_dispensed_ml = max(session.current_dispensed_ml, curr)

        session.last_volume_ml = curr

    @staticmethod
    def _resolve_unknown_mode(session: _ActiveSession, curr: int) -> None:
        if curr < session.initial_volume_ml:
            session.mode = MODE_DOSE
            session.preset_ml = session.initial_volume_ml
        elif curr > session.initial_volume_ml:
            session.mode = MODE_FULL_TANK
            session.preset_ml = None

    def _finalize_volume_on_stop(self, session: _ActiveSession, frame: IskraTelemetryFrame) -> None:
        if frame.completed_volume_ml is not None:
            session.current_dispensed_ml = frame.completed_volume_ml
            return
        curr = frame.volume_ml
        if session.mode == MODE_UNKNOWN:
            if curr < session.initial_volume_ml:
                session.mode = MODE_DOSE
                session.preset_ml = session.initial_volume_ml
            elif curr > 0:
                session.mode = MODE_FULL_TANK
                session.preset_ml = None

        if session.mode == MODE_DOSE:
            preset = session.preset_ml or session.initial_volume_ml
            if 0 <= curr <= preset:
                dispensed = preset - curr
                if dispensed > session.current_dispensed_ml:
                    session.current_dispensed_ml = dispensed
        elif session.mode == MODE_FULL_TANK:
            if curr > session.current_dispensed_ml:
                session.current_dispensed_ml = curr
