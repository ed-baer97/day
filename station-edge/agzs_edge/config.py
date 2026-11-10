"""Конфигурация станционного узла АГЗС (АСКА-02 + УЗГС-01)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

_DEFAULT_DISPENSER_NS = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def load_dotenv(path: Path) -> None:
    """Читает ключ=значение из .env в переменные окружения, не перезаписывая уже заданные."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _parse_addresses(raw: str) -> tuple[int, ...]:
    items: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        addr = int(token)
        if addr < 1 or addr > 6:
            raise ValueError(f"Адрес колонки Искра 1.72 должен быть в диапазоне 1..6, получено: {addr}")
        if addr not in items:
            items.append(addr)
    if not items:
        raise ValueError("Укажите хотя бы один адрес колонки в AGZS_PUMP_ADDRESSES (1..6)")
    return tuple(items)


def _parse_dispenser_map(raw: str, station_id: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for pair in raw.split(","):
        item = pair.strip()
        if not item or ":" not in item:
            continue
        addr_str, disp_uuid = item.split(":", 1)
        addr = int(addr_str.strip())
        UUID(disp_uuid.strip())  # валидация UUID
        mapping[addr] = disp_uuid.strip()
    # Для всех адресов 1..6 гарантируем детерминированный UUID, если он не задан явно
    base_uuid = UUID(station_id)
    for addr in range(1, 7):
        if addr not in mapping:
            mapping[addr] = str(uuid5(_DEFAULT_DISPENSER_NS, f"{base_uuid}:pump:{addr}"))
    return mapping


@dataclass(frozen=True)
class FrameLayout:
    """Калибровочная раскладка 23-байтного ответного кадра «Искра 1.72».

    Стандартная 23-байтная структура кадра ответа на команду «Тест» (код 4):
      [0]      : 0x01 (SOH — начало кадра)
      [1]      : Адрес колонки ASCII ('1'..'6', 0x31..0x36)
      [2]      : Код команды/ответа ASCII ('4', 0x34)
      [3..5]   : Состояние колонки (2 ASCII-символа, например '00'..'04')
      [5..7]   : Код ошибки протокола/аварии (2 ASCII-символа, например '00' или '06')
      [7..13]  : Поле цены, 6 ASCII-цифр (копейки/тыйны или сотые доли тенге)
      [13..19] : Поле объёма в миллилитрах, 6 ASCII-цифр (остаток дозы или налитые мл)
      [19..21] : Резерв / флаги режима (2 ASCII-символа)
      [21]     : 0x03 (ETX — конец текста кадра)
      [22]     : Контрольная сумма (BCC)

    При пусконаладке на живом стенде АСКА-02 смещения можно скорректировать
    без переписывания логики трекера и базы данных.
    """

    frame_length: int = 23
    soh_byte: int = 0x01
    etx_offset: int = 21
    etx_byte: int = 0x03
    bcc_offset: int = 22
    addr_offset: int = 1
    cmd_offset: int = 2
    state_slice: tuple[int, int] = (3, 5)
    error_slice: tuple[int, int] = (5, 7)
    price_slice: tuple[int, int] = (7, 13)
    volume_slice: tuple[int, int] = (13, 19)
    flags_slice: tuple[int, int] = (19, 21)
    checksum_mode: str = "xor"  # xor | sum7 | sum8 | any


@dataclass
class EdgeSettings:
    serial_port: str = "COM7"
    serial_baudrate: int = 9600
    serial_timeout_sec: float = 0.25
    pump_addresses: tuple[int, ...] = (1, 2)
    poll_interval_sec: float = 0.5
    source_mode: str = "serial"  # serial | emulator
    checksum_mode: str = "xor"
    db_path: Path = field(default_factory=lambda: Path("station_edge.db"))
    save_raw_frames: bool = False
    vps_base_url: str = "http://93.171.232.47"
    device_token: str = ""
    station_code: str = "AKT-12MKR"
    station_id: str = "a2222222-2222-2222-2222-222222222201"
    tank_id: str = "b2222222-2222-2222-2222-222222222201"
    dispenser_map: dict[int, str] = field(default_factory=dict)
    sync_enabled: bool = True
    sync_interval_sec: float = 5.0
    layout: FrameLayout = field(default_factory=FrameLayout)

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> "EdgeSettings":
        load_dotenv(dotenv_path or Path(".env"))
        serial_port = os.environ.get("AGZS_SERIAL_PORT", "COM7").strip() or "COM7"
        serial_baudrate = int(os.environ.get("AGZS_SERIAL_BAUDRATE", "9600").strip() or "9600")
        serial_timeout_sec = float(os.environ.get("AGZS_SERIAL_TIMEOUT_SEC", "0.25").strip() or "0.25")
        pump_addresses = _parse_addresses(os.environ.get("AGZS_PUMP_ADDRESSES", "1,2"))
        poll_interval_sec = float(os.environ.get("AGZS_POLL_INTERVAL_SEC", "0.5").strip() or "0.5")
        source_mode = os.environ.get("AGZS_SOURCE_MODE", "serial").strip().lower() or "serial"
        if source_mode not in {"serial", "emulator"}:
            raise ValueError("AGZS_SOURCE_MODE должен быть 'serial' или 'emulator'")

        checksum_mode = os.environ.get("AGZS_ISKRA_CHECKSUM_MODE", "xor").strip().lower() or "xor"
        if checksum_mode not in {"xor", "sum7", "sum8", "any"}:
            raise ValueError("AGZS_ISKRA_CHECKSUM_MODE должен быть xor, sum7, sum8 или any")

        db_path = Path(os.environ.get("AGZS_DB_PATH", "station_edge.db").strip() or "station_edge.db")
        save_raw = os.environ.get("AGZS_SAVE_RAW_FRAMES", "0").strip() in {"1", "true", "yes"}
        vps_base_url = (
            os.environ.get("AGZS_VPS_BASE_URL", "http://93.171.232.47").strip().rstrip("/")
            or "http://93.171.232.47"
        )
        device_token = os.environ.get("AGZS_DEVICE_TOKEN", "").strip()
        station_code = os.environ.get("AGZS_STATION_CODE", "AKT-12MKR").strip() or "AKT-12MKR"
        station_id = os.environ.get("AGZS_STATION_ID", "a2222222-2222-2222-2222-222222222201").strip()
        tank_id = os.environ.get("AGZS_TANK_ID", "b2222222-2222-2222-2222-222222222201").strip()
        UUID(station_id)
        if tank_id:
            UUID(tank_id)

        dispenser_map = _parse_dispenser_map(
            os.environ.get("AGZS_DISPENSER_MAP", ""),
            station_id,
        )
        sync_enabled = os.environ.get("AGZS_SYNC_ENABLED", "1").strip() not in {"0", "false", "no"}
        sync_interval_sec = float(os.environ.get("AGZS_SYNC_INTERVAL_SEC", "5.0").strip() or "5.0")

        layout = FrameLayout(checksum_mode=checksum_mode)
        return cls(
            serial_port=serial_port,
            serial_baudrate=serial_baudrate,
            serial_timeout_sec=serial_timeout_sec,
            pump_addresses=pump_addresses,
            poll_interval_sec=poll_interval_sec,
            source_mode=source_mode,
            checksum_mode=checksum_mode,
            db_path=db_path,
            save_raw_frames=save_raw,
            vps_base_url=vps_base_url,
            device_token=device_token,
            station_code=station_code,
            station_id=station_id,
            tank_id=tank_id,
            dispenser_map=dispenser_map,
            sync_enabled=sync_enabled,
            sync_interval_sec=sync_interval_sec,
            layout=layout,
        )

    def dispenser_uuid(self, address: int) -> str:
        if address in self.dispenser_map:
            return self.dispenser_map[address]
        return str(uuid5(_DEFAULT_DISPENSER_NS, f"{self.station_id}:pump:{address}"))
