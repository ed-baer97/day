"""Пульт колонок на уже существующем API.

Отдельный центр из кассового контура сюда не переносится. Колонки считает
эмулятор в памяти этого процесса: живого звена АСКА нет, команд на оборудование
нет. Законченный отпуск пишется в книгу резервуара тем же приёмом, что и
чтение Топаза. Kaspi и Webkassa не вызываются.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.schemas.ingest import DispenseIngest
from app.services.catalog import get_station
from app.services.device_ingest import accept_dispense, list_tank_devices

_ZONE = ZoneInfo("Asia/Qyzylorda")
_PRICE_KZT = 100
_FLOW_ML_PER_S = 200
_PUMP_COUNT = 2
_DISPENSERS = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

_CAPTIONS = {
    "IDLE": "СВОБОДНА",
    "RESERVED": "ДОЗА",
    "PAYMENT_PENDING": "ОЖИДАНИЕ",
    "READY": "ПУСК",
    "DISPENSING": "НАЛИВ",
    "COMPLETED": "ОТПУЩЕНО",
    "STOPPED": "СТОП",
    "ERROR": "АВАРИЯ",
    "MAINTENANCE": "РЕМОНТ",
    "OFFLINE": "ОТКЛЮЧЕНА",
}
_AXIS = {
    "order": "Заказ",
    "payment": "Оплата",
    "fiscal": "Чек",
    "dispensing": "Отпуск",
    "settlement": "Расчёт",
}
_VALUE = {
    "IDLE": "СВОБОДНА",
    "RESERVED": "ДОЗА",
    "PAYMENT_PENDING": "ОЖИДАНИЕ",
    "READY": "ПУСК",
    "DISPENSING": "НАЛИВ",
    "COMPLETED": "ОТПУЩЕНО",
    "STOPPED": "СТОП",
    "ERROR": "АВАРИЯ",
    "OFFLINE": "ОТКЛЮЧЕНА",
    "DRAFT": "создан",
    "CLOSED": "закрыт",
    "NONE": "нет",
    "CONFIRMED": "подтверждена",
    "NOT_STARTED": "не начат",
    "IN_PROGRESS": "налив",
    "NOT_READY": "не готов",
    "BALANCED": "сошлось",
    "ADJUSTMENT_REQUIRED": "расхождение",
    "COMPLETED_DOSE": "завершён",
    "STOPPED_DOSE": "остановлен",
}


class ManualClock:
    """Часы, которые двигает тест."""

    def __init__(self) -> None:
        self._now_ms = 0

    def now_ms(self) -> int:
        return self._now_ms

    def advance_ms(self, millis: int) -> None:
        if millis < 0:
            raise ValueError("Сдвиг часов задаётся неотрицательным числом миллисекунд")
        self._now_ms += millis


class SystemClock:
    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


def cost_kzt(delivered_ml: int, price_kzt_per_liter: int) -> int:
    if delivered_ml < 0 or price_kzt_per_liter < 0:
        raise ValueError("Объём и цена задаются неотрицательными целыми числами")
    return (delivered_ml * price_kzt_per_liter + 500) // 1000


def max_ml_for_prepaid(amount_kzt: int, price_kzt_per_liter: int) -> int:
    """Сколько миллилитров можно налить, чтобы округление не превысило предоплату."""

    if price_kzt_per_liter <= 0 or amount_kzt <= 0:
        return 0
    return (amount_kzt * 1000 + 499) // price_kzt_per_liter


def preset_kzt(buffer: str, mode: str, price_kzt_per_liter: int) -> int:
    text = buffer.strip().replace(",", ".")
    if not text or text == ".":
        raise HTTPException(status_code=409, detail="Введите дозу")
    if mode == "money":
        if not text.isdigit():
            raise HTTPException(status_code=409, detail="Сумма задаётся целыми тенге")
        amount = int(text)
        if amount <= 0:
            raise HTTPException(status_code=409, detail="Сумма дозы должна быть больше нуля")
        return amount
    if mode != "volume":
        raise HTTPException(status_code=422, detail="Неизвестный режим дозы")
    ml = _liters_to_ml(text)
    if ml <= 0:
        raise HTTPException(status_code=409, detail="Объём дозы должен быть больше нуля")
    amount = cost_kzt(ml, price_kzt_per_liter)
    if amount <= 0:
        raise HTTPException(status_code=409, detail="По этой цене объём не даёт даже одного тенге")
    return amount


def _liters_to_ml(text: str) -> int:
    if text.count(".") > 1:
        raise HTTPException(status_code=409, detail="Объём задаётся в литрах")
    if "." in text:
        whole, frac = text.split(".")
        if whole and not whole.isdigit():
            raise HTTPException(status_code=409, detail="Объём задаётся в литрах")
        if not frac.isdigit() or len(frac) > 2:
            raise HTTPException(status_code=409, detail="У объёма не больше двух знаков после запятой")
        hundredths = int(frac.ljust(2, "0")) if frac else 0
        return int(whole or "0") * 1000 + hundredths * 10
    if not text.isdigit():
        raise HTTPException(status_code=409, detail="Объём задаётся в литрах")
    return int(text) * 1000


def _change(left: str | None, right: str | None) -> str:
    start = _VALUE.get(left or "", left or "")
    end = _VALUE.get(right or "", right or "")
    if start and end and start != end:
        return f"{start} → {end}"
    return end or start


@dataclass
class _Dose:
    amount_kzt: int
    target_ml: int
    start_totalizer_ml: int
    stopped: bool = False


@dataclass
class _Sale:
    id: UUID
    number: str
    pump_id: UUID
    prepaid_kzt: int
    price_kzt_per_liter: int
    payment_status: str = "CONFIRMED"
    dispensing_status: str = "IN_PROGRESS"
    settlement_status: str = "NOT_READY"
    delivered_ml: int | None = None
    actual_kzt: int | None = None
    delta_kzt: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    message: str = "Допуск принят"


@dataclass
class _Pump:
    id: UUID
    address: str
    name: str
    price_kzt_per_liter: int
    flow_ml_per_s: int
    totalizer_ml: int = 0
    residue_ms: int = 0
    last_ms: int = 0
    logical: str = "IDLE"
    observation: str = "CONFIRMED"
    dose: _Dose | None = None
    sale_id: UUID | None = None
    settled_ml: int | None = None
    settled_kzt: int | None = None


@dataclass
class _Event:
    occurred_at: str
    pump_name: str
    sale_number: str
    title: str
    change: str
    detail: str


@dataclass
class _Incident:
    id: UUID
    severity: str
    code: str
    message: str
    pump_id: UUID | None
    sale_id: UUID | None
    occurred_at: str
    pump_name: str
    sale_number: str
    acknowledged: bool = False


@dataclass
class _Shift:
    id: UUID
    number: int
    status: str


class Desk:
    def __init__(self, station_id: UUID, clock: SystemClock | ManualClock) -> None:
        self.station_id = station_id
        self.clock = clock
        now = clock.now_ms()
        self.pumps = [
            _Pump(
                id=uuid4(),
                address=str(number),
                name=f"Колонка {number}",
                price_kzt_per_liter=_PRICE_KZT,
                flow_ml_per_s=_FLOW_ML_PER_S,
                last_ms=now,
            )
            for number in range(1, _PUMP_COUNT + 1)
        ]
        self.link_up = True
        self.latched = False
        self.shift: _Shift | None = None
        self._shift_seq = 0
        self._sale_seq = 0
        self.sales: dict[UUID, _Sale] = {}
        self.events: list[_Event] = []
        self.incidents: list[_Incident] = []
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            self._sync_all()
            return self._view()

    def tick(self) -> dict:
        with self._lock:
            self._sync_all()
            self._finish_ready()
            return self._view()

    def open_shift(self) -> dict:
        with self._lock:
            if self.shift is not None and self.shift.status == "open":
                return self._view()
            self._shift_seq += 1
            self.shift = _Shift(id=uuid4(), number=self._shift_seq, status="open")
            return self._view()

    def close_shift(self) -> tuple[str, dict]:
        with self._lock:
            self._sync_all()
            self._finish_ready()
            if self.shift is None or self.shift.status != "open":
                raise HTTPException(status_code=409, detail="Смена не открыта")
            if any(pump.logical in {"DISPENSING", "READY", "PAYMENT_PENDING"} for pump in self.pumps):
                raise HTTPException(
                    status_code=409,
                    detail="Смену нельзя закрыть, пока есть незавершённая оплата или отпуск",
                )
            self.shift.status = "closed"
            text = f"Смена {self.shift.number} закрыта"
            return text, self._view()

    def start(self, pump_id: UUID, mode: str, buffer: str) -> tuple[str, dict]:
        with self._lock:
            self._sync_all()
            if self.shift is None or self.shift.status != "open":
                raise HTTPException(status_code=409, detail="Смена не открыта")
            if self.latched:
                raise HTTPException(
                    status_code=409,
                    detail="Пуск запрещён. Нажмите «Разрешить пуск», когда колонку снова можно открывать.",
                )
            pump = self._pump(pump_id)
            sale = self.sales.get(pump.sale_id) if pump.sale_id else None
            if pump.logical == "DISPENSING":
                raise HTTPException(status_code=409, detail="Колонка не свободна или её состояние не подтверждено")
            if pump.logical == "PAYMENT_PENDING" and sale is not None and sale.payment_status == "CONFIRMED":
                self._authorize(pump, sale)
            else:
                if pump.logical != "IDLE" or pump.observation != "CONFIRMED":
                    raise HTTPException(
                        status_code=409,
                        detail="Колонка не свободна или её состояние не подтверждено",
                    )
                amount = preset_kzt(buffer, mode, pump.price_kzt_per_liter)
                sale = self._open_sale(pump, amount)
                self._authorize(pump, sale)
            self._sync_pump(pump)
            text = f"Пуск. {sale.message}"
            return text, self._view()

    def stop(self, pump_id: UUID) -> tuple[str, dict]:
        with self._lock:
            self._sync_all()
            pump = self._pump(pump_id)
            if pump.logical != "DISPENSING":
                raise HTTPException(
                    status_code=409,
                    detail="Колонка не в наливе. Клапан на оборудовании закрывается аппаратной кнопкой.",
                )
            if pump.dose is None:
                raise HTTPException(status_code=409, detail="Останавливать нечего: допуск не принят")
            pump.dose.stopped = True
            pump.residue_ms = 0
            self._finish_pump(pump)
            return "Налив на эмуляторе остановлен.", self._view()

    def set_latched(self, latched: bool) -> tuple[str, dict]:
        with self._lock:
            self.latched = latched
            if latched:
                text = "Новые команды запрещены. Для останова газа используйте аппаратную кнопку"
            else:
                text = "Пуск снова разрешён"
            return text, self._view()

    def set_link(self, up: bool) -> tuple[str, dict]:
        with self._lock:
            self._sync_all()
            self.link_up = up
            self._apply_link()
            if up:
                self._finish_ready()
                text = "Звено эмулятора восстановлено"
            else:
                text = "Звено эмулятора оборвано. Новые отпуски закрыты."
            return text, self._view()

    def journal(self) -> list[dict]:
        with self._lock:
            return [self._event_row(row) for row in self.events[:400]]

    def incident_rows(self) -> list[dict]:
        with self._lock:
            return [self._incident_row(row) for row in self.incidents[:200]]

    def cabinet(self) -> dict:
        with self._lock:
            self._sync_all()
            return self._cabinet_view()

    def set_price(self, price: int) -> dict:
        if price < 1:
            raise HTTPException(status_code=422, detail="укажите цену газа за литр")
        with self._lock:
            for pump in self.pumps:
                pump.price_kzt_per_liter = price
            return self._cabinet_view()

    def _cabinet_view(self) -> dict:
        finished = [
            sale
            for sale in self.sales.values()
            if sale.delivered_ml is not None and sale.actual_kzt is not None
        ]
        names = {pump.id: pump.name for pump in self.pumps}
        pumps = []
        for pump in self.pumps:
            rows = [sale for sale in finished if sale.pump_id == pump.id]
            pumps.append(
                {
                    "pump_id": str(pump.id),
                    "name": pump.name,
                    "delivered_ml": sum(sale.delivered_ml or 0 for sale in rows),
                    "amount_kzt": sum(sale.actual_kzt or 0 for sale in rows),
                    "sales": len(rows),
                }
            )
        recent = sorted(finished, key=lambda sale: sale.finished_at or sale.started_at, reverse=True)[:20]
        price = self.pumps[0].price_kzt_per_liter if self.pumps else _PRICE_KZT
        return {
            "station_id": self.station_id,
            "price_kzt_per_liter": price,
            "delivered_ml": sum(row["delivered_ml"] for row in pumps),
            "amount_kzt": sum(row["amount_kzt"] for row in pumps),
            "sales": sum(row["sales"] for row in pumps),
            "pumps": pumps,
            "recent": [
                {
                    "sale_id": str(sale.id),
                    "number": sale.number,
                    "pump_name": names.get(sale.pump_id, ""),
                    "delivered_ml": sale.delivered_ml,
                    "amount_kzt": sale.actual_kzt,
                    "price_kzt_per_liter": sale.price_kzt_per_liter,
                    "finished_at": (sale.finished_at or sale.started_at).isoformat(),
                }
                for sale in recent
            ],
        }

    def acknowledge(self, incident_id: UUID) -> dict:
        with self._lock:
            for row in self.incidents:
                if row.id == incident_id:
                    row.acknowledged = True
                    return self._incident_row(row)
        raise HTTPException(status_code=404, detail="Инцидент не найден")

    def _open_sale(self, pump: _Pump, amount: int) -> _Sale:
        station = get_station(self.station_id)
        self._sale_seq += 1
        local_day = datetime.now(_ZONE).strftime("%Y%m%d")
        sale = _Sale(
            id=uuid4(),
            number=f"{station.code}-{local_day}-{self._sale_seq:06d}",
            pump_id=pump.id,
            prepaid_kzt=amount,
            price_kzt_per_liter=pump.price_kzt_per_liter,
        )
        self.sales[sale.id] = sale
        pump.sale_id = sale.id
        pump.logical = "PAYMENT_PENDING"
        self._event(pump, sale, "order", None, "DRAFT", "Создана предоплата")
        self._event(pump, sale, "payment", "NONE", "CONFIRMED", "Учебная оплата. Kaspi ещё не подключён")
        self._event(
            pump,
            sale,
            "fiscal",
            None,
            None,
            "Чек Webkassa ещё не подключён, отпуск разрешён без чека",
        )
        return sale

    def _authorize(self, pump: _Pump, sale: _Sale) -> None:
        if pump.observation != "CONFIRMED" or not self.link_up:
            raise HTTPException(status_code=409, detail="Состояние колонки не подтверждено")
        if pump.dose is not None or pump.logical == "DISPENSING":
            raise HTTPException(status_code=409, detail="По продаже уже есть допуск, новый пуск запрещён")
        target = max_ml_for_prepaid(sale.prepaid_kzt, sale.price_kzt_per_liter)
        if target <= 0:
            sale.message = "Колонка отклонила допуск"
            sale.dispensing_status = "FAILED"
            raise HTTPException(status_code=409, detail="Колонка отклонила допуск")
        previous = pump.logical
        pump.settled_ml = None
        pump.settled_kzt = None
        pump.dose = _Dose(
            amount_kzt=sale.prepaid_kzt,
            target_ml=target,
            start_totalizer_ml=pump.totalizer_ml,
        )
        pump.logical = "DISPENSING"
        sale.dispensing_status = "IN_PROGRESS"
        sale.message = "Допуск принят"
        self._event(pump, sale, "dispensing", "NOT_STARTED", "IN_PROGRESS", "Идёт отпуск")
        self._pump_event(pump, sale, previous, "DISPENSING", "Допуск принят")

    def _finish_ready(self) -> None:
        if not self.link_up:
            return
        for pump in self.pumps:
            if pump.logical == "DISPENSING" and pump.dose is not None:
                physical = self._physical(pump)
                if physical in {"COMPLETED", "STOPPED"}:
                    self._finish_pump(pump)

    def _finish_pump(self, pump: _Pump) -> None:
        sale = self.sales.get(pump.sale_id) if pump.sale_id else None
        dose = pump.dose
        if sale is None or dose is None:
            pump.logical = "IDLE"
            pump.dose = None
            pump.sale_id = None
            return
        if pump.observation != "CONFIRMED":
            return
        delivered = pump.totalizer_ml - dose.start_totalizer_ml
        if delivered < 0:
            self._incident(pump, sale, "CRITICAL", "TOTALIZER_REGRESSION", "Счётчик уменьшился")
            pump.logical = "ERROR"
            sale.dispensing_status = "FAILED"
            pump.dose = None
            pump.sale_id = None
            return
        money = cost_kzt(delivered, sale.price_kzt_per_liter)
        delta = money - sale.prepaid_kzt
        physical = "STOPPED" if dose.stopped and delivered < dose.target_ml else "COMPLETED"
        if delta > 0:
            settlement = "NOT_READY"
            self._incident(pump, sale, "CRITICAL", "OVER_DELIVERY", "Фактическая стоимость больше предоплаты")
            next_status = "ERROR"
        elif delta < 0:
            settlement = "ADJUSTMENT_REQUIRED"
            self._incident(
                pump,
                sale,
                "WARNING",
                "SHORT_DELIVERY",
                "Фактическая стоимость меньше предоплаты",
            )
            next_status = "IDLE"
        else:
            settlement = "BALANCED"
            next_status = "IDLE"
        sale.delivered_ml = delivered
        sale.actual_kzt = money
        sale.delta_kzt = delta
        sale.finished_at = datetime.now(timezone.utc)
        pump.settled_ml = delivered
        pump.settled_kzt = money
        sale.settlement_status = settlement
        sale.dispensing_status = "STOPPED" if physical == "STOPPED" else "COMPLETED"
        end_label = "STOPPED_DOSE" if physical == "STOPPED" else "COMPLETED_DOSE"
        self._event(pump, sale, "dispensing", "IN_PROGRESS", end_label, "Факт снят со счётчика")
        self._event(pump, sale, "settlement", "NOT_READY", settlement, "Сравнение предоплаты и факта")
        self._event(pump, sale, "order", "DRAFT", "CLOSED", "Отпуск завершён")
        self._pump_event(pump, sale, "DISPENSING", next_status, "Результат записан")
        pump.logical = next_status
        pump.dose = None
        pump.sale_id = None
        self._post_book(pump, sale, delivered)

    def _post_book(self, pump: _Pump, sale: _Sale, delivered_ml: int) -> None:
        if delivered_ml <= 0:
            return
        tanks = list_tank_devices(self.station_id)
        if not tanks:
            return
        tank = tanks[0]
        accept_dispense(
            DispenseIngest(
                station_id=self.station_id,
                dispenser_id=uuid5(_DISPENSERS, f"{self.station_id}:{pump.address}"),
                tank_id=tank.tank_id,
                volume_liters=delivered_ml / 1000,
                started_at=sale.started_at,
                finished_at=datetime.now(timezone.utc),
                external_txn_id=str(sale.id),
            )
        )

    def _sync_all(self) -> None:
        for pump in self.pumps:
            self._sync_pump(pump)
        self._apply_link()

    def _sync_pump(self, pump: _Pump) -> None:
        now = self.clock.now_ms()
        elapsed = now - pump.last_ms
        if elapsed < 0:
            elapsed = 0
        pump.last_ms = now
        if elapsed and pump.dose is not None and not pump.dose.stopped:
            pump.residue_ms += pump.flow_ml_per_s * elapsed
            added = pump.residue_ms // 1000
            pump.residue_ms %= 1000
            room = pump.dose.target_ml - (pump.totalizer_ml - pump.dose.start_totalizer_ml)
            if added >= room:
                added = room
                pump.residue_ms = 0
            if added > 0:
                pump.totalizer_ml += added

    def _apply_link(self) -> None:
        quality = "CONFIRMED" if self.link_up else "UNKNOWN"
        for pump in self.pumps:
            pump.observation = quality

    def _physical(self, pump: _Pump) -> str:
        if pump.dose is None:
            return "IDLE"
        delivered = pump.totalizer_ml - pump.dose.start_totalizer_ml
        if pump.dose.stopped and delivered < pump.dose.target_ml:
            return "STOPPED"
        if delivered >= pump.dose.target_ml:
            return "COMPLETED"
        return "DISPENSING"

    def _pump(self, pump_id: UUID) -> _Pump:
        for pump in self.pumps:
            if pump.id == pump_id:
                return pump
        raise HTTPException(status_code=404, detail="Колонка не найдена")

    def _event(
        self,
        pump: _Pump,
        sale: _Sale,
        axis: str,
        left: str | None,
        right: str | None,
        detail: str,
    ) -> None:
        self.events.insert(
            0,
            _Event(
                occurred_at=datetime.now(timezone.utc).isoformat(),
                pump_name=pump.name,
                sale_number=sale.number,
                title=_AXIS.get(axis, axis),
                change=_change(left, right) if right else detail,
                detail=detail,
            ),
        )
        del self.events[400:]

    def _pump_event(self, pump: _Pump, sale: _Sale, left: str, right: str, detail: str) -> None:
        self.events.insert(
            0,
            _Event(
                occurred_at=datetime.now(timezone.utc).isoformat(),
                pump_name=pump.name,
                sale_number=sale.number,
                title="Колонка",
                change=_change(left, right),
                detail=detail,
            ),
        )
        del self.events[400:]

    def _incident(self, pump: _Pump, sale: _Sale, severity: str, code: str, message: str) -> None:
        self.incidents.insert(
            0,
            _Incident(
                id=uuid4(),
                severity=severity,
                code=code,
                message=message,
                pump_id=pump.id,
                sale_id=sale.id,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                pump_name=pump.name,
                sale_number=sale.number,
            ),
        )
        del self.incidents[200:]

    def _view(self) -> dict:
        station = get_station(self.station_id)
        return {
            "station_id": self.station_id,
            "station_name": station.name,
            "emulator": True,
            "link_up": self.link_up,
            "commands_latched": self.latched,
            "shift": None
            if self.shift is None
            else {"shift_id": str(self.shift.id), "number": self.shift.number, "status": self.shift.status},
            "pumps": [self._pump_view(pump) for pump in self.pumps],
        }

    def _pump_view(self, pump: _Pump) -> dict:
        sale = self.sales.get(pump.sale_id) if pump.sale_id else None
        confirmed = pump.observation == "CONFIRMED"
        dose_ml = None
        provisional = None
        totalizer = pump.totalizer_ml if confirmed else None
        if confirmed and pump.dose is not None:
            dose_ml = pump.totalizer_ml - pump.dose.start_totalizer_ml
            if sale is not None:
                provisional = cost_kzt(dose_ml, sale.price_kzt_per_liter)
        elif confirmed and pump.settled_ml is not None and pump.logical in {"IDLE", "COMPLETED", "STOPPED"}:
            dose_ml = pump.settled_ml
            provisional = pump.settled_kzt
        return {
            "pump_id": str(pump.id),
            "name": pump.name,
            "address": pump.address,
            "status": pump.logical,
            "observation_quality": pump.observation,
            "price_kzt_per_liter": pump.price_kzt_per_liter,
            "dose_ml": dose_ml,
            "totalizer_ml": totalizer,
            "provisional_kzt": provisional,
            "sale_id": None if sale is None else str(sale.id),
            "payment_status": None if sale is None else sale.payment_status,
        }

    def _event_row(self, row: _Event) -> dict:
        return {
            "occurred_at": row.occurred_at,
            "pump_name": row.pump_name,
            "sale_number": row.sale_number,
            "title": row.title,
            "change": row.change,
            "detail": row.detail,
        }

    def _incident_row(self, row: _Incident) -> dict:
        return {
            "incident_id": str(row.id),
            "severity": row.severity,
            "code": row.code,
            "message": row.message,
            "pump_id": None if row.pump_id is None else str(row.pump_id),
            "sale_id": None if row.sale_id is None else str(row.sale_id),
            "occurred_at": row.occurred_at,
            "pump_name": row.pump_name,
            "sale_number": row.sale_number,
            "acknowledged": row.acknowledged,
        }


_guard = threading.Lock()
_desks: dict[UUID, Desk] = {}


def reset_consoles() -> None:
    with _guard:
        _desks.clear()


def use_manual_clock(station_id: UUID) -> ManualClock:
    get_station(station_id)
    clock = ManualClock()
    with _guard:
        _desks[station_id] = Desk(station_id, clock)
    return clock


def advance_for_tests(station_id: UUID, millis: int) -> dict:
    desk = _existing(station_id)
    clock = desk.clock
    if not isinstance(clock, ManualClock):
        raise RuntimeError("Сдвигать можно только испытательные часы")
    clock.advance_ms(millis)
    return desk.tick()


def _existing(station_id: UUID) -> Desk:
    get_station(station_id)
    with _guard:
        desk = _desks.get(station_id)
        if desk is None:
            desk = Desk(station_id, SystemClock())
            _desks[station_id] = desk
        return desk


def console_snapshot(station_id: UUID) -> dict:
    return _existing(station_id).snapshot()


def console_tick(station_id: UUID) -> dict:
    return _existing(station_id).tick()


def console_open_shift(station_id: UUID) -> dict:
    return _existing(station_id).open_shift()


def console_close_shift(station_id: UUID) -> tuple[str, dict]:
    return _existing(station_id).close_shift()


def console_start(station_id: UUID, pump_id: UUID, mode: str, buffer: str) -> tuple[str, dict]:
    return _existing(station_id).start(pump_id, mode, buffer)


def console_stop(station_id: UUID, pump_id: UUID) -> tuple[str, dict]:
    return _existing(station_id).stop(pump_id)


def console_latch(station_id: UUID, latched: bool) -> tuple[str, dict]:
    return _existing(station_id).set_latched(latched)


def console_link(station_id: UUID, up: bool) -> tuple[str, dict]:
    return _existing(station_id).set_link(up)


def console_journal(station_id: UUID) -> list[dict]:
    return _existing(station_id).journal()


def console_cabinet(station_id: UUID) -> dict:
    return _existing(station_id).cabinet()


def console_set_price(station_id: UUID, price: int) -> dict:
    return _existing(station_id).set_price(price)


def console_incidents(station_id: UUID) -> list[dict]:
    return _existing(station_id).incident_rows()


def console_acknowledge(station_id: UUID, incident_id: UUID) -> dict:
    return _existing(station_id).acknowledge(incident_id)
