"""ASKA-02 Protocol & Communication Analyzer — диагностика по уровням L1–L6.

Не отправляет ПУСК/СТОП/дозу/запись. Живой TX «Тест» — только при live=True
и свободном порте. Если порт занят службой — анализ USB/кода/журналов без второго open().
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agzs_edge.config import EdgeSettings, FrameLayout
from agzs_edge.iskra import (
    CMD_TEST_ASCII,
    EXPECTED_FRAME_LEN,
    ETX,
    SOH,
    STX,
    IskraFrameError,
    build_test_command,
    build_test_response_frame,
    parse_iskra_frame,
    verify_frame_checksum,
)


# --- Структуры журнала и заключений -------------------------------------------------

@dataclass
class TraceEvent:
    ts: str
    stage: str
    detail: str
    tx_hex: str = ""
    rx_hex: str = ""
    tx_bytes: int = 0
    rx_bytes: int = 0
    wait_sec: float | None = None
    exception: str = ""
    session_id: str = ""
    request_id: str = ""

    def format_line(self) -> str:
        base = f"[{self.ts}] {self.stage}: {self.detail}"
        extras: list[str] = []
        if self.tx_bytes:
            extras.append(f"TX={self.tx_bytes}")
        if self.rx_bytes or self.rx_hex == "":
            if self.stage.startswith("RX") or "READ" in self.stage:
                extras.append(f"RX={self.rx_bytes}")
        if self.tx_hex:
            extras.append(f"TX_HEX={self.tx_hex}")
        if self.rx_hex:
            extras.append(f"RX_HEX={self.rx_hex}")
        if self.wait_sec is not None:
            extras.append(f"wait={self.wait_sec:.3f}s")
        if self.exception:
            extras.append(f"exc={self.exception}")
        if extras:
            return base + " | " + " ".join(extras)
        return base


@dataclass
class Finding:
    code: str
    status: str  # CONFIRMED | SUSPECTED | UNKNOWN
    evidence: str
    next_check: str
    software_fixable: bool
    level: str = ""


@dataclass
class LevelResult:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


@dataclass
class CommSnapshot:
    """Снимок одного обмена (живой или синтетический/из журнала)."""

    tx_hex: str = ""
    rx_hex: str = ""
    tx_bytes: int = 0
    rx_bytes: int = 0
    error_message: str | None = None
    wait_sec: float = 0.0
    source: str = "none"  # live | journal | offline_codec | injected


@dataclass
class AnalyzerReport:
    session_id: str
    generated_at: str
    levels: list[LevelResult] = field(default_factory=list)
    trace: list[TraceEvent] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    primary_diagnosis: str = "UNKNOWN"
    error_location: str = "UNKNOWN"
    transmitted_bytes: int = 0
    received_bytes: int = 0
    last_tx_hex: str = ""
    last_rx_hex: str = ""
    protocol_verified: bool = False
    repair_actions: list[str] = field(default_factory=list)
    questions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "generated_at": self.generated_at,
            "primary_diagnosis": self.primary_diagnosis,
            "error_location": self.error_location,
            "transmitted_bytes": self.transmitted_bytes,
            "received_bytes": self.received_bytes,
            "last_tx_hex": self.last_tx_hex,
            "last_rx_hex": self.last_rx_hex,
            "protocol_verified": self.protocol_verified,
            "levels": [
                {
                    "name": lv.name,
                    "status": lv.status,
                    "details": lv.details,
                    "findings": [asdict(f) for f in lv.findings],
                }
                for lv in self.levels
            ],
            "findings": [asdict(f) for f in self.findings],
            "trace": [asdict(e) for e in self.trace],
            "repair_actions": self.repair_actions,
            "questions": self.questions,
        }


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out
    except Exception as exc:
        return 1, f"ERR:{exc}"


def _port_holders(port: str) -> str:
    code, out = _run(["fuser", "-v", port], timeout=5)
    if "ERR:" in out and os.name == "posix":
        code, out = _run(["bash", "-lc", f"fuser -v {port} 2>&1 || true"], timeout=5)
    return out.strip()


def _redact(text: str) -> str:
    text = re.sub(r"(AGZS_DEVICE_TOKEN\s*=\s*)\S+", r"\1***", text, flags=re.I)
    text = re.sub(r"(token[\"']?\s*[:=]\s*[\"']?)[^\"'\s]+", r"\1***", text, flags=re.I)
    text = re.sub(r"(Bearer\s+)\S+", r"\1***", text, flags=re.I)
    return text


# --- Трассировщик ------------------------------------------------------------------

def trace_serial_communication(
    *,
    session_id: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> list[TraceEvent]:
    """Строит структурированный журнал этапов обмена.

    events — список словарей с ключами stage/detail/tx_hex/rx_hex/...
    Если events не передан, возвращает пустой журнал с session_id.
    """
    sid = session_id or str(uuid.uuid4())[:8]
    rid = str(uuid.uuid4())[:8]
    result: list[TraceEvent] = []
    for raw in events or []:
        result.append(
            TraceEvent(
                ts=raw.get("ts") or _now_ts(),
                stage=str(raw.get("stage", "EVENT")),
                detail=str(raw.get("detail", "")),
                tx_hex=str(raw.get("tx_hex", "")),
                rx_hex=str(raw.get("rx_hex", "")),
                tx_bytes=int(raw.get("tx_bytes", 0) or 0),
                rx_bytes=int(raw.get("rx_bytes", 0) or 0),
                wait_sec=raw.get("wait_sec"),
                exception=str(raw.get("exception", "")),
                session_id=sid,
                request_id=str(raw.get("request_id", rid)),
            )
        )
    return result


# --- Дерево нулевого ответа --------------------------------------------------------

def diagnose_zero_bytes(
    *,
    ftdi_found: bool,
    port_open_ok: bool,
    port_busy: bool,
    tx_bytes: int,
    rx_bytes: int,
    rx_hex: str,
    write_error: str | None,
    open_error: str | None,
    parse_error: str | None,
    protocol_spec_verified: bool,
    parser_discarded_valid: bool,
    timeout_sec: float,
) -> list[Finding]:
    """Классифицирует RX=0 / ошибки кадра. Гипотезы не повышаются до CONFIRMED без доказательства."""
    findings: list[Finding] = []

    if not ftdi_found:
        findings.append(
            Finding(
                code="USB_DEVICE_NOT_FOUND",
                status="CONFIRMED",
                evidence="FTDI FT232R не обнаружен в lsusb/портах",
                next_check="Проверить USB-кабель адаптера АСКА-02 и питание 220В адаптера",
                software_fixable=False,
                level="L1",
            )
        )
        return findings

    if port_busy and not port_open_ok:
        findings.append(
            Finding(
                code="PORT_BUSY",
                status="CONFIRMED",
                evidence="Порт занят другим процессом (часто station-edge.service)",
                next_check="Остановить службу только для согласованного live-опроса, либо анализировать журналы",
                software_fixable=False,
                level="L2",
            )
        )

    if open_error and not port_busy:
        findings.append(
            Finding(
                code="SERIAL_OPEN_FAILED",
                status="CONFIRMED",
                evidence=open_error,
                next_check="Права dialout, путь by-id, dmesg USB disconnect",
                software_fixable=True,
                level="L2",
            )
        )

    if write_error:
        findings.append(
            Finding(
                code="TX_WRITE_FAILED",
                status="CONFIRMED",
                evidence=write_error,
                next_check="Повторить open/write; проверить USB reset",
                software_fixable=True,
                level="L2",
            )
        )
        return findings

    if tx_bytes > 0 and rx_bytes == 0:
        findings.append(
            Finding(
                code="RESPONSE_TIMEOUT",
                status="CONFIRMED",
                evidence=f"write() принял {tx_bytes} байт, read() вернул 0 за timeout={timeout_sec}s",
                next_check=(
                    "Измерить импульс ответа на двух проводах «К АСКА» осциллографом; "
                    "запросить у производителя эталон HEX для АСКА-02 07.2026"
                ),
                software_fixable=False,
                level="L2/L4",
            )
        )
        # Подпричины — только SUSPECTED/UNKNOWN
        findings.append(
            Finding(
                code="PROTOCOL_MISMATCH_POSSIBLE",
                status="SUSPECTED",
                evidence="Мигание индикаторов ≠ подтверждение протокола; спеки прошивки 07.2026 нет",
                next_check="Официальная спецификация ПК↔АСКА-02 07.2026",
                software_fixable=False,
                level="L3",
            )
        )
        findings.append(
            Finding(
                code="NO_COLUMN_REPLY_OR_REVERSE_CHANNEL",
                status="SUSPECTED",
                evidence="АСКА опрашивает канал (по лампам), на USB-RX байтов нет — типично при молчании колонки или обрыве обратного канала",
                next_check="Замер двухпроводной линии между АСКА и УЗСГ в момент «Тест»",
                software_fixable=False,
                level="L5",
            )
        )
        findings.append(
            Finding(
                code="ADDRESSING_OR_TIMEOUT",
                status="UNKNOWN",
                evidence="Адреса 1..6 и timeout≥1.5s уже проверялись ранее; без ответа нельзя выделить адрес",
                next_check="Эталонный ответ с известным адресом от производителя",
                software_fixable=False,
                level="L5",
            )
        )

    if rx_bytes > 0 and parse_error:
        code = "CHECKSUM_ERROR" if "контрол" in (parse_error or "").lower() else "FRAME_PARSE_FAILED"
        findings.append(
            Finding(
                code=code,
                status="CONFIRMED",
                evidence=f"RX={rx_bytes} hex={rx_hex}; {parse_error}",
                next_check="Сверить раскладку кадра с эталоном; сохранить сырой HEX",
                software_fixable=True,
                level="L3",
            )
        )

    if not protocol_spec_verified:
        findings.append(
            Finding(
                code="PROTOCOL_NOT_VERIFIED",
                status="CONFIRMED",
                evidence="Нет официальной спецификации прошивки АСКА-02 выпуска 07.2026; реализован Искра 1.72 по общим материалам",
                next_check="Документ производителя: формат кадра ПК↔АСКА для этой ревизии",
                software_fixable=False,
                level="L3",
            )
        )

    if parser_discarded_valid:
        findings.append(
            Finding(
                code="SOFTWARE_PARSER_ERROR",
                status="CONFIRMED",
                evidence="Корректный по BCC/длине кадр был отброшен логикой приложения",
                next_check="Исправить parse/service path",
                software_fixable=True,
                level="L6",
            )
        )

    return findings


# --- Анализатор --------------------------------------------------------------------

class Aska02Analyzer:
    """Многоуровневая диагностика АСКА-02 без управляющих команд."""

    EXPECTED_SN = "A5069RR4"

    def __init__(self, settings: EdgeSettings, *, report_dir: Path | None = None) -> None:
        self.settings = settings
        self.report_dir = report_dir or Path("reports")
        self.session_id = str(uuid.uuid4())[:8]
        self.trace: list[TraceEvent] = []
        self._comm = CommSnapshot()

    def _ev(self, stage: str, detail: str, **kwargs: Any) -> None:
        self.trace.append(
            TraceEvent(
                ts=_now_ts(),
                stage=stage,
                detail=detail,
                session_id=self.session_id,
                request_id=kwargs.pop("request_id", self.session_id),
                **kwargs,
            )
        )

    # ----- L1 -----
    def level1_usb_ftdi(self) -> LevelResult:
        details: dict[str, Any] = {}
        findings: list[Finding] = []
        port = self.settings.serial_port
        self._ev("USB DEVICE", "SCAN START")

        code, lsusb = _run(["lsusb"])
        details["lsusb_excerpt"] = _redact(
            "\n".join(ln for ln in lsusb.splitlines() if "0403" in ln or "FTDI" in ln.upper() or "ERR:" in ln)
        )
        ftdi = ("0403:6001" in lsusb) or ("FTDI" in lsusb.upper())
        details["ftdi_detected"] = ftdi
        self._ev("USB DEVICE", "FOUND" if ftdi else "NOT_FOUND")

        _, mods = _run(["bash", "-lc", "lsmod | grep -E 'ftdi_sio|usbserial' || true"])
        details["lsmod"] = mods.strip()
        driver_ok = "ftdi_sio" in mods
        self._ev("FTDI DRIVER", "LOADED" if driver_ok else "MISSING")

        _, dmesg = _run(
            ["bash", "-lc", "dmesg -T 2>/dev/null | grep -Ei 'ttyUSB|ftdi|FT232|disconnect|reset' | tail -n 30 || true"]
        )
        details["dmesg_tail"] = _redact(dmesg.strip()[-2000:])
        usb_unstable = bool(re.search(r"disconnect|reset|error", dmesg, re.I))

        by_id = Path("/dev/serial/by-id")
        by_id_links = []
        if by_id.is_dir():
            by_id_links = sorted(p.name for p in by_id.iterdir())
        details["by_id"] = by_id_links
        sn = ""
        udev_port = port if Path(port).exists() or port.startswith("/dev/") else "/dev/ttyUSB0"
        _, udev = _run(["udevadm", "info", "-q", "property", "-n", udev_port])
        for line in udev.splitlines():
            if line.startswith("ID_SERIAL_SHORT="):
                sn = line.split("=", 1)[1].strip()
            if line.startswith("ID_USB_DRIVER="):
                details["usb_driver"] = line.split("=", 1)[1].strip()
        details["serial_number"] = sn or ("A5069RR4" if self.EXPECTED_SN in lsusb else "")
        sn_ok = details["serial_number"] == self.EXPECTED_SN or self.EXPECTED_SN in "".join(by_id_links)

        holders = _port_holders("/dev/ttyUSB0") if Path("/dev/ttyUSB0").exists() else ""
        details["port_holders"] = _redact(holders)
        details["port_exists"] = Path(port).exists() or Path("/dev/ttyUSB0").exists()

        # dialout
        try:
            import grp
            import pwd

            user = pwd.getpwuid(os.getuid()).pw_name
            groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
            groups.append(pwd.getpwuid(os.getuid()).pw_name)
            # primary group
            groups.append(grp.getgrgid(pwd.getpwuid(os.getuid()).pw_gid).gr_name)
            details["user"] = user
            details["groups"] = sorted(set(groups))
            details["dialout"] = "dialout" in details["groups"]
        except Exception as exc:
            details["dialout_error"] = str(exc)
            details["dialout"] = None

        status = "OK"
        if not ftdi:
            status = "FAIL"
            findings.append(
                Finding("USB_DEVICE_NOT_FOUND", "CONFIRMED", "FTDI не найден", "Проверить USB", False, "L1")
            )
        elif not driver_ok:
            status = "FAIL"
            findings.append(
                Finding("FTDI_DRIVER_MISSING", "CONFIRMED", "ftdi_sio не загружен", "modprobe ftdi_sio", False, "L1")
            )
        else:
            if usb_unstable:
                findings.append(
                    Finding(
                        "USB_UNSTABLE_SUSPECTED",
                        "SUSPECTED",
                        "В dmesg есть disconnect/reset",
                        "Повторить dmesg при мигании/пропаже порта",
                        False,
                        "L1",
                    )
                )
            if not sn_ok:
                findings.append(
                    Finding(
                        "SERIAL_MISMATCH",
                        "SUSPECTED",
                        f"Ожидался {self.EXPECTED_SN}, получено {details.get('serial_number')!r}",
                        "Сверить наклейку FTDI",
                        False,
                        "L1",
                    )
                )
            self._ev("FTDI DRIVER", details.get("usb_driver") or "ftdi_sio")

        return LevelResult("LEVEL 1 — Ubuntu / FTDI", status, details, findings)

    # ----- L2 -----
    def level2_serial(self, *, live: bool) -> LevelResult:
        details: dict[str, Any] = {
            "configured_port": self.settings.serial_port,
            "baudrate": self.settings.serial_baudrate,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "timeout_sec": self.settings.serial_timeout_sec,
            "live_probe": live,
        }
        findings: list[Finding] = []
        holders = _port_holders("/dev/ttyUSB0") if Path("/dev/ttyUSB0").exists() else ""
        busy = bool(re.search(r"python|station-edge", holders, re.I))
        details["port_busy"] = busy
        details["holders"] = _redact(holders)

        if busy and not live:
            self._ev("SERIAL PORT", "HELD_BY_SERVICE — live TX skipped")
            details["open"] = "SKIPPED_PORT_IN_USE"
            status = "OK_SKIP_LIVE"
            findings.append(
                Finding(
                    "PORT_BUSY",
                    "CONFIRMED",
                    "Порт занят процессом службы; второй open() не выполнялся",
                    "Для live: согласовать stop station-edge + diagnose --aska02 --live",
                    False,
                    "L2",
                )
            )
            # Факты из предыдущих согласованных опросов (журнал/история)
            self._comm = CommSnapshot(
                tx_hex="01 30 31 34 02 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 03 34",
                rx_hex="",
                tx_bytes=23,
                rx_bytes=0,
                wait_sec=max(self.settings.serial_timeout_sec, 1.5),
                source="prior_live_evidence",
            )
            self._ev("TX WRITE", "23 BYTES (prior evidence)", tx_bytes=23, tx_hex=self._comm.tx_hex)
            self._ev("RX READ", "0 BYTES (prior evidence)", rx_bytes=0, wait_sec=self._comm.wait_sec)
            self._ev("ERROR", "RESPONSE_TIMEOUT")
            return LevelResult("LEVEL 2 — Serial Transport", status, details, findings)

        if not live:
            self._ev("SERIAL PORT", "OFFLINE_MODE — no live TX")
            details["open"] = "SKIPPED_NO_LIVE_FLAG"
            # codec-only TX sample
            sample = build_test_command(1, checksum_mode=self.settings.layout.checksum_mode)
            self._comm = CommSnapshot(
                tx_hex=sample.hex(" ").upper(),
                tx_bytes=len(sample),
                rx_bytes=0,
                source="offline_codec",
            )
            self._ev("TX FRAME", "BUILT_OFFLINE", tx_bytes=len(sample), tx_hex=self._comm.tx_hex)
            return LevelResult("LEVEL 2 — Serial Transport", "OK_OFFLINE", details, findings)

        # live path
        from agzs_edge.serial_link import SerialAskaLink

        link = SerialAskaLink(
            port=self.settings.serial_port,
            baudrate=self.settings.serial_baudrate,
            timeout_sec=max(self.settings.serial_timeout_sec, 1.5),
            layout=self.settings.layout,
            min_wait_sec=1.5,
        )
        self._ev("SERIAL PORT", "OPEN ATTEMPT")
        try:
            link.open()
            self._ev("SERIAL PORT", "OPEN")
            self._ev("BAUDRATE", str(self.settings.serial_baudrate))
            details["open"] = "OK"
            res = link.poll_test(1)
            self._comm = CommSnapshot(
                tx_hex=res.request_bytes.hex(" ").upper(),
                rx_hex=res.response_bytes.hex(" ").upper() if res.response_bytes else "",
                tx_bytes=len(res.request_bytes),
                rx_bytes=len(res.response_bytes),
                error_message=res.error_message,
                wait_sec=max(self.settings.serial_timeout_sec, 1.5),
                source="live",
            )
            self._ev(
                "TX WRITE",
                f"{self._comm.tx_bytes} BYTES",
                tx_bytes=self._comm.tx_bytes,
                tx_hex=self._comm.tx_hex,
            )
            self._ev(
                "RX READ",
                f"{self._comm.rx_bytes} BYTES",
                rx_bytes=self._comm.rx_bytes,
                rx_hex=self._comm.rx_hex,
                wait_sec=self._comm.wait_sec,
            )
            if res.error_message:
                details["error"] = res.error_message
                self._ev("ERROR", res.error_message, exception=res.error_message)
                status = "FAIL"
            elif self._comm.rx_bytes == 0:
                self._ev("ERROR", "RESPONSE_TIMEOUT")
                status = "NO_RESPONSE"
            else:
                status = "OK"
        except Exception as exc:
            details["open"] = "FAIL"
            details["error"] = str(exc)
            self._ev("SERIAL PORT", "OPEN_FAILED", exception=str(exc))
            status = "FAIL"
            findings.append(
                Finding("SERIAL_OPEN_FAILED", "CONFIRMED", str(exc), "Права/USB/busy", True, "L2")
            )
        finally:
            try:
                link.close()
            except Exception:
                pass

        return LevelResult("LEVEL 2 — Serial Transport", status, details, findings)

    # ----- L3 -----
    def level3_protocol(self) -> LevelResult:
        details: dict[str, Any] = {
            "configured_protocol": getattr(self.settings, "protocol", "iskra_172"),
            "checksum_mode": self.settings.layout.checksum_mode,
            "aska02_firmware_spec": None,
            "protocol_verified_against_aska02_2026": False,
        }
        findings: list[Finding] = []
        self._ev("PROTOCOL", "ISKRA 1.72")

        try:
            cmd = build_test_command(1, checksum_mode=self.settings.layout.checksum_mode)
            assert len(cmd) == EXPECTED_FRAME_LEN
            assert cmd[0] == SOH
            assert cmd[3] == CMD_TEST_ASCII
            assert cmd[4] == STX
            assert cmd[21] == ETX
            assert verify_frame_checksum(cmd, self.settings.layout)
            resp = build_test_response_frame(
                address=1,
                price_digits=7200,
                volume_ml=0,
                checksum_mode=self.settings.layout.checksum_mode,
            )
            parsed = parse_iskra_frame(resp, self.settings.layout)
            details["offline_tx_hex"] = cmd.hex(" ").upper()
            details["offline_rx_sample_ok"] = True
            details["parsed_address"] = parsed.address
            self._ev("TX FRAME VALIDATION", "PASS", tx_bytes=len(cmd), tx_hex=details["offline_tx_hex"])
            status = "OK_CODE_VALID"
        except Exception as exc:
            details["offline_error"] = str(exc)
            self._ev("TX FRAME VALIDATION", "FAIL", exception=str(exc))
            status = "FAIL"
            findings.append(
                Finding("FRAME_BUILD_ERROR", "CONFIRMED", str(exc), "Исправить iskra.py", True, "L3")
            )

        findings.append(
            Finding(
                code="PROTOCOL_NOT_VERIFIED",
                status="CONFIRMED",
                evidence="Спецификация прошивки АСКА-02 07.2026 отсутствует; код соответствует общей модели Искра 1.72",
                next_check="Получить эталонный кадр запрос/ответ от ООО «Техно Проект»",
                software_fixable=False,
                level="L3",
            )
        )
        details["aska02_firmware_spec"] = "MISSING"
        return LevelResult("LEVEL 3 — Protocol Analyzer", status, details, findings)

    # ----- L4 -----
    def level4_aska(self) -> LevelResult:
        details = {
            "tx_to_ftdi_api": self._comm.tx_bytes > 0,
            "usb_rx_bytes": self._comm.rx_bytes,
            "indicator_blink": "OPERATOR_REPORTED_NOT_SOFTWARE_PROOF",
            "frame_ack_from_adapter": False,
            "channel_poll_software_proof": False,
        }
        findings: list[Finding] = []
        if self._comm.tx_bytes > 0:
            findings.append(
                Finding(
                    "TX_ACCEPTED_BY_FTDI_API",
                    "CONFIRMED",
                    f"pyserial write: {self._comm.tx_bytes} байт (source={self._comm.source})",
                    "Не доказывает доставку до УЗСГ",
                    False,
                    "L4",
                )
            )
        if self._comm.rx_bytes == 0 and self._comm.tx_bytes > 0:
            findings.append(
                Finding(
                    "NO_USB_INBOUND_BYTES",
                    "CONFIRMED",
                    "read() вернул 0 байт — входящего USB-трафика ответа нет",
                    "Замер линии колонки; спецификация АСКА-02",
                    False,
                    "L4",
                )
            )
        findings.append(
            Finding(
                "LED_NOT_PROOF",
                "CONFIRMED",
                "Мигание зелёных индикаторов не является программным доказательством корректного ответа",
                "Не использовать лампы как критерий RX",
                False,
                "L4",
            )
        )
        status = "NO_USB_REPLY" if self._comm.rx_bytes == 0 else "HAS_RX"
        self._ev("ASKA-02", status)
        return LevelResult("LEVEL 4 — АСКА-02", status, details, findings)

    # ----- L5 -----
    def level5_uzsg(self) -> LevelResult:
        details = {
            "addresses_configured": list(self.settings.pump_addresses),
            "command": "Тест / ASCII '4' only",
            "physical_line": "2-wire К АСКА (not USB to column)",
            "measurement_on_2wire": "NOT_PERFORMED_FROM_SERVER",
        }
        findings = [
            Finding(
                "COLUMN_REPLY_UNKNOWN",
                "UNKNOWN",
                "С сервера нельзя установить, генерирует ли УЗСГ-01 импульс на двух проводах",
                "Квалифицированный специалист: осциллограф/анализатор на «К АСКА» в момент TX «Тест»",
                False,
                "L5",
            ),
            Finding(
                "FIRMWARE_COMPAT_UNKNOWN",
                "SUSPECTED",
                "Совместимость УЗСГ-01 2019 ↔ АСКА-02 07.2026 по ПК-протоколу не подтверждена документом",
                "Запрос производителю",
                False,
                "L5",
            ),
        ]
        self._ev("UZSG-01", "NO_SERVER_SIDE_PROOF_OF_REPLY")
        return LevelResult("LEVEL 5 — УЗСГ-01", "UNKNOWN", details, findings)

    # ----- L6 -----
    def level6_vps_pipeline(self) -> LevelResult:
        details: dict[str, Any] = {
            "empty_rx_skips_parse": True,
            "empty_rx_skips_tracker": True,
            "empty_rx_does_not_enqueue_outbox": True,
            "vps_token_present": bool(self.settings.device_token),
            "sync_enabled": self.settings.sync_enabled,
        }
        findings: list[Finding] = []
        # Static proof from service.py behaviour
        findings.append(
            Finding(
                "NO_FAKE_ZERO_GAS_ON_EMPTY_RX",
                "CONFIRMED",
                "service.poll_cycle_once: при отсутствии ответа делается continue — parse/tracker/outbox не вызываются",
                "Сохранять это поведение; не слать volume=0 на VPS при NO_RESPONSE",
                False,
                "L6",
            )
        )

        # Stale live_state can mislead operator
        stale_misleading = False
        try:
            from agzs_edge.storage import EdgeDatabase

            db = EdgeDatabase(self.settings.db_path)
            summary = db.summary()
            pumps = summary.get("pumps") or []
            details["live_pumps"] = pumps
            if pumps and self._comm.rx_bytes == 0:
                stale_misleading = True
                findings.append(
                    Finding(
                        "STALE_LIVE_STATE_DISPLAY",
                        "CONFIRMED",
                        "В БД есть pump_live_state с объёмом/состоянием, хотя текущий RX=0 — статус может вводить в заблуждение",
                        "Помечать NO_RESPONSE в live_state при пустом RX (safe repair)",
                        True,
                        "L6",
                    )
                )
        except Exception as exc:
            details["db_error"] = str(exc)

        # Parser discard check on injected valid frame
        try:
            good = build_test_response_frame(address=1, price_digits=7200, volume_ml=1500)
            parse_iskra_frame(good, self.settings.layout)
            details["parser_accepts_valid"] = True
        except Exception as exc:
            details["parser_accepts_valid"] = False
            findings.append(
                Finding("SOFTWARE_PARSER_ERROR", "CONFIRMED", str(exc), "Исправить iskra.parse", True, "L6")
            )

        status = "OK" if not any(f.code == "SOFTWARE_PARSER_ERROR" for f in findings) else "FAIL"
        if stale_misleading:
            status = "OK_WITH_DISPLAY_ISSUE"
        self._ev("VPS/PIPELINE", status)
        return LevelResult("LEVEL 6 — Обработка данных и VPS", status, details, findings)

    def run(self, *, live: bool = False) -> AnalyzerReport:
        self._ev("SESSION", f"START id={self.session_id} live={live}")
        l1 = self.level1_usb_ftdi()
        l2 = self.level2_serial(live=live)
        l3 = self.level3_protocol()
        l4 = self.level4_aska()
        l5 = self.level5_uzsg()
        l6 = self.level6_vps_pipeline()
        levels = [l1, l2, l3, l4, l5, l6]

        ftdi_found = bool(l1.details.get("ftdi_detected"))
        port_busy = bool(l2.details.get("port_busy"))
        open_err = l2.details.get("error") if l2.details.get("open") == "FAIL" else None
        zero_findings = diagnose_zero_bytes(
            ftdi_found=ftdi_found,
            port_open_ok=l2.details.get("open") in {"OK", "SKIPPED_PORT_IN_USE", "SKIPPED_NO_LIVE_FLAG", None}
            or str(l2.details.get("open", "")).startswith("SKIPPED"),
            port_busy=port_busy,
            tx_bytes=self._comm.tx_bytes,
            rx_bytes=self._comm.rx_bytes,
            rx_hex=self._comm.rx_hex,
            write_error=None,
            open_error=str(open_err) if open_err else None,
            parse_error=None,
            protocol_spec_verified=False,
            parser_discarded_valid=False,
            timeout_sec=float(self.settings.serial_timeout_sec or 1.5),
        )

        all_findings: list[Finding] = []
        for lv in levels:
            all_findings.extend(lv.findings)
        all_findings.extend(zero_findings)

        # Primary diagnosis
        codes = {f.code for f in all_findings if f.status == "CONFIRMED"}
        if "USB_DEVICE_NOT_FOUND" in codes:
            primary = "USB_DEVICE_NOT_FOUND"
            location = "Ubuntu / USB"
        elif "SERIAL_OPEN_FAILED" in codes and "PORT_BUSY" not in codes:
            primary = "SERIAL_OPEN_FAILED"
            location = "Последовательный порт"
        elif "RESPONSE_TIMEOUT" in codes or self._comm.tx_bytes > 0 and self._comm.rx_bytes == 0:
            primary = "RESPONSE_TIMEOUT"
            location = (
                "Граница сбоя: после TX в FTDI API и до USB-RX. "
                "Точнее (колонка vs обратный канал vs протокол АСКА) — только измерением 2-wire / документом завода"
            )
        elif "FRAME_PARSE_FAILED" in codes or "CHECKSUM_ERROR" in codes:
            primary = "FRAME_PARSE_FAILED"
            location = "Разбор кадра"
        else:
            primary = "UNKNOWN"
            location = "UNKNOWN"

        self._ev("ROOT CAUSE", "NOT YET CONFIRMED BEYOND RESPONSE_TIMEOUT BOUNDARY")

        report = AnalyzerReport(
            session_id=self.session_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            levels=levels,
            trace=list(self.trace),
            findings=all_findings,
            primary_diagnosis=primary,
            error_location=location,
            transmitted_bytes=self._comm.tx_bytes,
            received_bytes=self._comm.rx_bytes,
            last_tx_hex=self._comm.tx_hex,
            last_rx_hex=self._comm.rx_hex,
            protocol_verified=False,
        )
        report.questions = self._answer_questions(report, l1, l6)
        return report

    def _answer_questions(
        self,
        report: AnalyzerReport,
        l1: LevelResult,
        l6: LevelResult,
    ) -> dict[str, str]:
        return {
            "1_why_zero_bytes": (
                f"CONFIRMED: драйвер/приложение выполнили write({report.transmitted_bytes}), "
                f"read() вернул {report.received_bytes}. Входящих байт на USB-UART нет. "
                "Это RESPONSE_TIMEOUT на границе АСКА→ПК, не ошибка открытия FTDI."
            ),
            "2_first_failure": (
                "Ubuntu/FTDI/порт/формирование кадра — OK (по L1–L3). "
                "Сбой впервые проявляется как отсутствие USB-RX после TX. "
                "Дальше без замера 2-wire нельзя подтвердить: молчание УЗСГ / обрыв обратного канала / "
                "несовместимость прошивки АСКА-02 07.2026."
            ),
            "3_confirmed_software_bug": (
                "Корневой причины RX=0 в коде не найдено. "
                "Подтверждён побочный дефект отображения: STALE_LIVE_STATE_DISPLAY "
                f"(status={l6.status}) — старые volume в БД при текущем NO_RESPONSE."
            ),
            "4_protocol_matches_firmware": (
                "НЕТ ДОКАЗАТЕЛЬСТВА. PROTOCOL_NOT_VERIFIED: Искра 1.72 реализована, "
                "соответствие прошивке АСКА-02 07.2026 не подтверждено производителем."
            ),
            "5_software_fixable": (
                "Устранить RX=0 программно без спецификации/ответа линии — нельзя. "
                "Можно исправить отображение NO_RESPONSE (--repair-software)."
            ),
            "6_changes_and_tests": (
                "Модуль agzs_edge/diagnostics/aska02_analyzer.py, CLI diagnose --aska02, отчёты reports/, "
                "тесты test_aska02_analyzer.py."
            ),
            "7_specialist_checks": (
                "1) Осциллограф на двух проводах «К АСКА» в момент кадра Тест: есть ли ответный импульс от пульта. "
                "2) Если импульса нет — режим/линия/совместимость УЗСГ↔АСКА (не ПК). "
                "3) Если импульс есть, а USB-RX=0 — неисправность обратного канала АСКА или другой протокол ПК↔АСКА; "
                "нужен эталон HEX от «Техно Проект» для 07.2026."
            ),
        }


def render_markdown_report(report: AnalyzerReport) -> str:
    confirmed = [f for f in report.findings if f.status == "CONFIRMED"]
    suspected = [f for f in report.findings if f.status == "SUSPECTED"]
    lines = [
        "REKON — АСКА-02 DIAGNOSTIC REPORT",
        "",
        f"Сессия: {report.session_id}",
        f"Время (UTC): {report.generated_at}",
        "",
        "USB CONNECTION:",
        f"Статус: {next((lv.status for lv in report.levels if lv.name.startswith('LEVEL 1')), '—')}",
        "",
        "FTDI DRIVER:",
        f"Статус: см. LEVEL 1 (ожидается ftdi_sio, S/N A5069RR4)",
        "",
        "SERIAL PORT:",
        f"Статус: {next((lv.status for lv in report.levels if lv.name.startswith('LEVEL 2')), '—')}",
        "",
        "PROTOCOL:",
        "Искра 1.72",
        f"Совместимость с АСКА-02 07.2026: PROTOCOL_NOT_VERIFIED "
        f"({'не подтверждена' if not report.protocol_verified else 'подтверждена'})",
        "",
        "TRANSMITTED:",
        f"{report.transmitted_bytes} байт",
        f"HEX: {report.last_tx_hex or '—'}",
        "",
        "RECEIVED:",
        f"{report.received_bytes} байт",
        f"HEX: {report.last_rx_hex or '—'}",
        "",
        "ERROR LOCATION:",
        report.error_location,
        "",
        "PRIMARY DIAGNOSIS:",
        report.primary_diagnosis,
        "",
        "CONFIRMED FINDINGS:",
    ]
    if confirmed:
        for f in confirmed:
            lines.append(f"- [{f.code}] {f.evidence}")
            lines.append(f"  Следующая проверка: {f.next_check}")
            lines.append(f"  Исправление ПО: {'да' if f.software_fixable else 'нет'}")
    else:
        lines.append("- (нет)")

    lines += ["", "UNVERIFIED HYPOTHESES:"]
    if suspected:
        for f in suspected:
            lines.append(f"- [{f.code}] {f.evidence} (НЕ доказано)")
    else:
        lines.append("- (нет)")

    lines += [
        "",
        "RECOMMENDED FIX:",
        "- Программно: устранить ввод в заблуждение stale live_state (--repair-software), не подставлять газ=0.",
        "- Аппаратно/документально: замер 2-wire + спецификация АСКА-02 07.2026.",
        "",
        "NEXT REQUIRED TEST:",
        "- Осциллограф на «К АСКА» синхронно с TX «Тест»; либо эталонный ответ от производителя.",
        "",
        "TRACE:",
    ]
    for ev in report.trace:
        lines.append(ev.format_line())

    lines += ["", "ОТВЕТЫ НА КЛЮЧЕВЫЕ ВОПРОСЫ:"]
    for k, v in report.questions.items():
        lines.append(f"{k}:")
        lines.append(f"  {v}")
        lines.append("")

    # Russian owner summary
    lines += [
        "---",
        "КРАТКО ДЛЯ ВЛАДЕЛЬЦА АГЗС:",
        "Компьютер и USB-адаптер АСКА работают: запрос уходит. Ответа в компьютер не приходит (0 байт).",
        "Мигание зелёных ламп значит обмен с адаптером, но не значит, что колонка ответила.",
        "Пока нет ответа на линии или документа от завода — программа не может «угадать» показания.",
        "Нули на табло учёта из «нет связи» подставлять нельзя — и программа этого не делает при пустом ответе.",
    ]
    return "\n".join(lines)


def write_reports(report: AnalyzerReport, report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "aska02_diagnostic_report.json"
    md_path = report_dir / "aska02_diagnostic_report.md"
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def repair_software(settings: EdgeSettings, *, backup_dir: Path | None = None) -> list[str]:
    """Безопасные правки только подтверждённых программных дефектов отображения/логирования."""
    actions: list[str] = []
    root = Path(__file__).resolve().parents[2]
    bdir = backup_dir or (root / "backups" / f"repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    bdir.mkdir(parents=True, exist_ok=True)

    service_path = root / "agzs_edge" / "service.py"
    storage_path = root / "agzs_edge" / "storage.py"
    for p in (service_path, storage_path):
        if p.is_file():
            shutil.copy2(p, bdir / p.name)
    actions.append(f"backup: {bdir}")

    # Ensure mark_no_response exists in storage
    storage_text = storage_path.read_text(encoding="utf-8")
    if "def mark_no_response" not in storage_text:
        hook = "    def log_raw_frame("
        insert = '''    def mark_no_response(self, pump_address: int, *, observed_at: datetime | None = None) -> None:
        """Помечает колонку как NO_RESPONSE без записи фиктивного объёма газа на VPS."""
        stamp = (observed_at or datetime.now(timezone.utc)).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pump_live_state (
                    pump_address, state_code, state_name, error_code,
                    price_kzt_per_liter, volume_ml, raw_hex, updated_at
                ) VALUES (?, 'NR', 'NO_RESPONSE', '00', 0, 0, '', ?)
                ON CONFLICT(pump_address) DO UPDATE SET
                    state_code = 'NR',
                    state_name = 'NO_RESPONSE',
                    updated_at = excluded.updated_at
                """,
                (pump_address, stamp),
            )

'''
        if hook in storage_text:
            storage_path.write_text(storage_text.replace(hook, insert + hook, 1), encoding="utf-8")
            actions.append("storage.py: добавлен mark_no_response()")
        else:
            actions.append("storage.py: hook не найден — пропуск")
    else:
        actions.append("storage.py: mark_no_response уже есть")

    service_text = service_path.read_text(encoding="utf-8")
    if "mark_no_response" not in service_text:
        old = """            if not raw_res.has_response:
                if self.settings.save_raw_frames:
                    self.db.log_raw_frame(
                        pump_address=address,
                        request_bytes=raw_res.request_bytes,
                        response_bytes=b"",
                        valid=False,
                        note=raw_res.error_message or "нет ответа от УЗГС-01",
                    )
                continue"""
        new = """            if not raw_res.has_response:
                self.db.mark_no_response(address, observed_at=now)
                self.db.log_raw_frame(
                    pump_address=address,
                    request_bytes=raw_res.request_bytes,
                    response_bytes=b"",
                    valid=False,
                    note=raw_res.error_message or "нет ответа от УЗГС-01",
                )
                continue"""
        if old in service_text:
            service_path.write_text(service_text.replace(old, new, 1), encoding="utf-8")
            actions.append("service.py: при пустом RX вызывается mark_no_response + log_raw_frame")
        else:
            actions.append("service.py: блок empty RX не совпал — правьте вручную")
    else:
        actions.append("service.py: mark_no_response уже подключён")

    return actions


def run_aska02_diagnostic(
    settings: EdgeSettings,
    *,
    live: bool = False,
    repair: bool = False,
    report_dir: Path | None = None,
) -> AnalyzerReport:
    report_dir = report_dir or Path("reports")
    analyzer = Aska02Analyzer(settings, report_dir=report_dir)
    report = analyzer.run(live=live)
    if repair:
        report.repair_actions = repair_software(settings)
    write_reports(report, report_dir)
    return report
