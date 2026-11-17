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


def _resolve_preferred_port(configured: str) -> str:
    """Предпочитает стабильный /dev/serial/by-id/ для FTDI, если он есть."""
    import glob
    from pathlib import Path

    if configured.startswith("/dev/serial/by-id/"):
        return configured
    by_id = sorted(glob.glob("/dev/serial/by-id/*FTDI*") + glob.glob("/dev/serial/by-id/*A5069RR4*"))
    if by_id:
        return by_id[0]
    if Path(configured).exists() or configured.upper().startswith("COM"):
        return configured
    return configured


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

    Кадр «Тест» Искра 1.72, 23 байта:
      [0]      : 0x01 (SOH)
      [1..3]   : номер ТРК, две ASCII-цифры ('01'..'06')
      [3]      : код команды ASCII ('4')
      [4]      : 0x02 (STX)
      [5..11]  : цена, 6 ASCII-цифр
      [11..17] : объём, 6 ASCII-цифр (остаток дозы или налитые мл)
      [17..19] : ошибка протокола, 2 ASCII-символа
      [19..21] : код состояния ТРК, 2 ASCII-символа
      [21]     : 0x03 (ETX)
      [22]     : CRC, XOR байтов после SOH, включая ETX

    При пусконаладке на живом стенде АСКА-02 смещения можно скорректировать
    без переписывания логики трекера и базы данных.
    """

    frame_length: int = 23
    soh_byte: int = 0x01
    etx_offset: int = 21
    etx_byte: int = 0x03
    bcc_offset: int = 22
    addr_offset: int = 1
    cmd_offset: int = 3
    state_slice: tuple[int, int] = (19, 21)
    error_slice: tuple[int, int] = (17, 19)
    price_slice: tuple[int, int] = (5, 11)
    volume_slice: tuple[int, int] = (11, 17)
    flags_slice: tuple[int, int] = (19, 21)
    checksum_mode: str = "xor"  # xor | sum7 | sum8 | any


@dataclass
class EdgeSettings:
    serial_port: str = "COM7"
    serial_baudrate: int = 9600
    serial_timeout_sec: float = 1.0
    pump_addresses: tuple[int, ...] = (1, 2)
    poll_interval_sec: float = 0.5
    source_mode: str = "serial"  # serial | emulator
    protocol: str = "iskra_172"  # только подтверждённые: iskra_172
    checksum_mode: str = "xor"
    read_only: bool = True
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
        serial_timeout_sec = float(os.environ.get("AGZS_SERIAL_TIMEOUT_SEC", "1.5").strip() or "1.5")
        pump_addresses = _parse_addresses(os.environ.get("AGZS_PUMP_ADDRESSES", "1,2"))
        poll_interval_sec = float(os.environ.get("AGZS_POLL_INTERVAL_SEC", "0.5").strip() or "0.5")
        source_mode = os.environ.get("AGZS_SOURCE_MODE", "serial").strip().lower() or "serial"
        if source_mode not in {"serial", "emulator"}:
            raise ValueError("AGZS_SOURCE_MODE должен быть 'serial' или 'emulator'")

        protocol = os.environ.get("AGZS_PROTOCOL", "iskra_172").strip().lower() or "iskra_172"
        if protocol not in {"iskra_172"}:
            raise ValueError(
                "AGZS_PROTOCOL: разрешён только iskra_172. "
                "aska02_native не активирован — нет подтверждённой спецификации прошивки АСКА-02 07.2026"
            )
        read_only = os.environ.get("AGZS_READ_ONLY", "1").strip() not in {"0", "false", "no"}
        if not read_only:
            raise ValueError("AGZS_READ_ONLY=0 запрещён: узел работает только на чтение")

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
        # Предпочитаем стабильный by-id на Linux, если порт задан как ttyUSB*
        if serial_port.startswith("/dev/ttyUSB"):
            serial_port = _resolve_preferred_port(serial_port)

        return cls(
            serial_port=serial_port,
            serial_baudrate=serial_baudrate,
            serial_timeout_sec=serial_timeout_sec,
            pump_addresses=pump_addresses,
            poll_interval_sec=poll_interval_sec,
            source_mode=source_mode,
            protocol=protocol,
            checksum_mode=checksum_mode,
            read_only=read_only,
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
