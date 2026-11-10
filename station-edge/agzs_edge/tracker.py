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
        session = self._active.get(addr)

        # 1. Если заправка ещё не активна
        if session is None:
            if frame.state_code == STATE_DOSE_SET and frame.volume_ml > 0:
                # На пульте УЗГС-01 набрали дозу перед пуском (например, 20 000 мл)
                self._staged_preset_ml[addr] = frame.volume_ml
                return None

            if frame.state_code == STATE_DISPENSING:
                staged_preset = self._staged_preset_ml.pop(addr, None)
                # Определяем начальный режим, если возможно сразу
                if staged_preset is not None and staged_preset > 0 and frame.volume_ml <= staged_preset:
                    mode = MODE_DOSE
                    preset_ml = staged_preset
                    dispensed_ml = max(0, preset_ml - frame.volume_ml)
                elif frame.flags_raw == "01":
                    # Явный флаг режима дозы в кадре
                    mode = MODE_DOSE
                    preset_ml = frame.volume_ml
                    dispensed_ml = 0
                elif frame.flags_raw == "02":
                    # Явный флаг режима «до полного»
                    mode = MODE_FULL_TANK
                    preset_ml = None
                    dispensed_ml = frame.volume_ml
                elif frame.volume_ml == 0:
                    # Старт с 0 мл — это «до полного»
                    mode = MODE_FULL_TANK
                    preset_ml = None
                    dispensed_ml = 0
                else:
                    # Первое наблюдение налива с ненулевым числом (например, задали 20 000 мл без кадра DOSE_SET
                    # либо заметили уже начавшийся налив «до полного»). Точный режим выяснится на следующем шаге
                    # по направлению изменения числа (уменьшается -> доза, растёт -> до полного).
                    mode = MODE_UNKNOWN
                    preset_ml = frame.volume_ml
                    dispensed_ml = 0

                self._active[addr] = _ActiveSession(
                    pump_address=addr,
                    started_at=now,
                    initial_volume_ml=frame.volume_ml,
                    preset_ml=preset_ml,
                    mode=mode,
                    current_dispensed_ml=dispensed_ml,
                    last_volume_ml=frame.volume_ml,
                    price_kzt_per_liter=frame.price_kzt_per_liter,
                    last_state_code=frame.state_code,
                    last_error_code=frame.error_code,
                    last_raw_frame_hex=frame.raw_hex,
                )
            return None

        # 2. Заправка уже идёт — обновляем расчёт миллилитров
        self._update_session_volume(session, frame)

        # Если налив продолжается — ничего не закрываем
        if frame.state_code == STATE_DISPENSING:
            return None

        # 3. Переход из DISPENSING в завершающее состояние (COMPLETED, STOPPED, IDLE, ERROR)
        finished_session = self._active.pop(addr)
        self._staged_preset_ml.pop(addr, None)

        # Если при переходе в COMPLETED/STOPPED в кадре пришёл финальный остаток (например 0 при полной выдаче дозы
        # или итоговые миллилитры при «до полного»), учитываем его, но не затираем сбросом в 0 при переходе сразу в IDLE
        if frame.state_code in {STATE_COMPLETED, STATE_STOPPED, STATE_ERROR}:
            self._finalize_volume_on_stop(finished_session, frame)
        elif frame.state_code == STATE_IDLE and finished_session.mode == MODE_DOSE and frame.volume_ml == 0:
            # В режиме обычной дозы 0 в конце означает, что остаток дозы выбран полностью
            if finished_session.preset_ml is not None:
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

        return CompletedDispense(
            external_txn_id=txn_id,
            pump_address=addr,
            mode=final_mode,
            preset_ml=finished_session.preset_ml if final_mode == MODE_DOSE else None,
            dispensed_ml=finished_session.current_dispensed_ml,
            volume_liters=round(finished_session.current_dispensed_ml / 1000.0, 3),
            price_kzt_per_liter=finished_session.price_kzt_per_liter,
            final_state_code=frame.state_code,
            error_code=frame.error_code if frame.error_code != "00" else finished_session.last_error_code,
            started_at=finished_session.started_at,
            finished_at=now,
            last_raw_frame_hex=frame.raw_hex,
        )

    def _update_session_volume(self, session: _ActiveSession, frame: IskraTelemetryFrame) -> None:
        if frame.price_kzt_per_liter > 0:
            session.price_kzt_per_liter = frame.price_kzt_per_liter
        session.last_state_code = frame.state_code
        if frame.error_code != "00":
            session.last_error_code = frame.error_code
        session.last_raw_frame_hex = frame.raw_hex

        if frame.state_code != STATE_DISPENSING:
            return

        curr = frame.volume_ml
        prev = session.last_volume_ml

        if session.mode == MODE_UNKNOWN:
            if curr < session.initial_volume_ml:
                # Поле уменьшается -> это обычная доза (остаток убывает от initial_volume_ml)
                session.mode = MODE_DOSE
                session.preset_ml = session.initial_volume_ml
            elif curr > session.initial_volume_ml:
                # Поле увеличивается -> это налив «до полного»
                session.mode = MODE_FULL_TANK
                session.preset_ml = None

        if session.mode == MODE_DOSE:
            preset = session.preset_ml or session.initial_volume_ml
            if curr <= preset:
                dispensed = preset - curr
                if dispensed > session.current_dispensed_ml:
                    session.current_dispensed_ml = dispensed
        elif session.mode == MODE_FULL_TANK:
            if curr >= session.current_dispensed_ml:
                session.current_dispensed_ml = curr
        else:
            # Пока режим ещё не определился (первый кадр без сдвига)
            session.last_volume_ml = prev

        session.last_volume_ml = curr

    def _finalize_volume_on_stop(self, session: _ActiveSession, frame: IskraTelemetryFrame) -> None:
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
