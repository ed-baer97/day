"""Касса пульта. Окно вызывает те же методы, а смена и отпуск уходят на API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from agzs_station.application.views import IncidentView, JournalEntry, PumpView, SaleView, ShiftView


class CashierService:
    def __init__(self, api_base: str, station_code: str, *, training: bool) -> None:
        self.training = training
        self.actor_id: str | None = None
        self._api = _Api(api_base)
        self._station_code = station_code
        self._station_id = ""
        self._desk: dict | None = None
        self._sales: dict[str, SaleView] = {}

    def login(self, display_name: str, password: str) -> None:
        session = self._api.call("POST", "/auth/login", {"username": display_name, "password": password})
        if not isinstance(session, dict) or not session.get("token"):
            raise RuntimeError("Сервер не выдал сессию")
        if session.get("role") != "console" or not session.get("station_id"):
            raise RuntimeError(
                "Пульт входит логином администратора пульта. Его создаёт владелец заправки, не администратор платформы."
            )
        self._api.token = str(session["token"])
        self._station_id = str(session["station_id"])
        self.actor_id = display_name or "owner"
        self._desk = self._expect_desk(self._api.call("GET", self._path("")))

    def open_shift(self) -> ShiftView:
        self._require_login()
        self._desk = self._expect_desk(self._api.call("POST", self._path("/shift/open")))
        return self._shift()

    def close_shift(self) -> ShiftView:
        self._require_login()
        result = self._api.call("POST", self._path("/shift/close"))
        self._desk = self._expect_desk(result)
        return self._shift()

    def tick(self) -> None:
        if self.actor_id is None:
            return
        self._desk = self._expect_desk(self._api.call("POST", self._path("/tick")))

    def pumps(self) -> list[PumpView]:
        desk = self._require_desk()
        rows = desk.get("pumps") or []
        return [PumpView(**{field: row.get(field) for field in PumpView.__dataclass_fields__}) for row in rows]

    def commands_latched(self) -> bool:
        desk = self._desk or {}
        return bool(desk.get("commands_latched"))

    def begin_prepay(self, pump_id: str, amount_kzt: int) -> SaleView:
        self._require_training()
        result = self._api.call(
            "POST",
            self._path(f"/pumps/{pump_id}/start"),
            {"mode": "money", "buffer": str(amount_kzt)},
        )
        return self._remember_sale(pump_id, result)

    def take_payment(self, sale_id: str) -> SaleView:
        return self._known_sale(sale_id)

    def open_dispense_gate(self, sale_id: str) -> SaleView:
        pump = self._pump_of(sale_id)
        if pump is not None and pump.status == "PAYMENT_PENDING" and pump.payment_status == "CONFIRMED":
            result = self._api.call(
                "POST",
                self._path(f"/pumps/{pump.pump_id}/start"),
                {"mode": "money", "buffer": ""},
            )
            return self._remember_sale(pump.pump_id, result)
        return self._known_sale(sale_id)

    def continue_dispense(self, sale_id: str) -> SaleView:
        pump = self._pump_of(sale_id)
        if pump is None:
            raise RuntimeError("Продажа на колонке не найдена")
        result = self._api.call(
            "POST",
            self._path(f"/pumps/{pump.pump_id}/start"),
            {"mode": "money", "buffer": ""},
        )
        return self._remember_sale(pump.pump_id, result)

    def training_stop_early(self, address: str) -> None:
        pump = next((row for row in self.pumps() if row.address == address), None)
        if pump is None:
            raise RuntimeError("Колонка не найдена")
        result = self._api.call("POST", self._path(f"/pumps/{pump.pump_id}/stop"))
        self._take_desk(result)

    def latch_commands(self) -> str:
        return self._command(True)

    def release_commands(self) -> str:
        return self._command(False)

    def training_cut_link(self) -> None:
        self._take_desk(self._api.call("POST", self._path("/link"), {"up": False}))

    def training_restore_link(self) -> None:
        self._take_desk(self._api.call("POST", self._path("/link"), {"up": True}))

    def events(self) -> list[JournalEntry]:
        rows = self._api.call("GET", self._path("/journal"))
        if not isinstance(rows, list):
            return []
        return [JournalEntry(**{field: row.get(field, "") for field in JournalEntry.__dataclass_fields__}) for row in rows]

    def incidents(self) -> list[IncidentView]:
        rows = self._api.call("GET", self._path("/incidents"))
        if not isinstance(rows, list):
            return []
        return [
            IncidentView(**{field: row.get(field) for field in IncidentView.__dataclass_fields__})
            for row in rows
        ]

    def acknowledge_incident(self, incident_id: str) -> None:
        self._api.call("POST", self._path(f"/incidents/{incident_id}/acknowledge"))

    def station_timezone(self) -> str:
        return "Asia/Qyzylorda"

    def _command(self, latched: bool) -> str:
        result = self._api.call("POST", self._path("/commands"), {"latched": latched})
        self._take_desk(result)
        if isinstance(result, dict) and isinstance(result.get("message"), str):
            return result["message"]
        return "Пуск снова разрешён" if not latched else "Новые команды запрещены"

    def _remember_sale(self, pump_id: str, result: object) -> SaleView:
        self._take_desk(result)
        message = ""
        if isinstance(result, dict) and isinstance(result.get("message"), str):
            message = result["message"]
            if message.startswith("Пуск. "):
                message = message.removeprefix("Пуск. ")
        pump = next((row for row in self.pumps() if row.pump_id == pump_id), None)
        sale_id = pump.sale_id if pump and pump.sale_id else pump_id
        sale = SaleView(
            sale_id=sale_id,
            display_number="",
            pump_id=pump_id,
            order_status="DRAFT",
            payment_status=pump.payment_status if pump and pump.payment_status else "CONFIRMED",
            fiscal_status="SKIPPED",
            dispensing_status="IN_PROGRESS",
            settlement_status="NOT_READY",
            prepaid_kzt=0,
            unit_price_kzt_per_liter=pump.price_kzt_per_liter if pump else 0,
            actual_kzt=None,
            delta_kzt=None,
            delivered_ml=pump.dose_ml if pump else None,
            message=message or "Допуск принят",
        )
        self._sales[sale.sale_id] = sale
        return sale

    def _known_sale(self, sale_id: str) -> SaleView:
        sale = self._sales.get(sale_id)
        if sale is None:
            raise RuntimeError("Продажа на колонке не найдена")
        return sale

    def _pump_of(self, sale_id: str) -> PumpView | None:
        for pump in self.pumps():
            if pump.sale_id == sale_id:
                return pump
        return None

    def _shift(self) -> ShiftView:
        desk = self._require_desk()
        shift = desk.get("shift") or {}
        return ShiftView(
            shift_id=str(shift.get("shift_id") or ""),
            number=int(shift.get("number") or 0),
            status=str(shift.get("status") or "closed"),
        )

    def _take_desk(self, result: object) -> None:
        self._desk = self._expect_desk(result)

    def _expect_desk(self, result: object) -> dict:
        if isinstance(result, dict) and isinstance(result.get("desk"), dict):
            return result["desk"]
        if isinstance(result, dict) and "pumps" in result:
            return result
        raise RuntimeError("Сервер вернул непонятный ответ")

    def _require_desk(self) -> dict:
        if self._desk is None:
            raise RuntimeError("Сначала войдите")
        return self._desk

    def _require_login(self) -> None:
        if self.actor_id is None or not self._station_id:
            raise RuntimeError("Сначала войдите")

    def _require_training(self) -> None:
        if not self.training:
            raise RuntimeError("Продажа в промышленном профиле не создаётся: нет допуска АСКА-02")

    def _path(self, suffix: str) -> str:
        return f"/stations/{self._station_id}/console{suffix}"


class _Api:
    def __init__(self, base: str) -> None:
        self.base = base
        self.token = ""

    def call(self, method: str, path: str, payload: dict | None = None) -> object:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            detail = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed.get("detail"), str):
                    detail = parsed["detail"]
            except json.JSONDecodeError:
                pass
            raise RuntimeError(detail or exc.reason) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Сервер не ответил") from exc
        if not raw:
            return None
        return json.loads(raw)
