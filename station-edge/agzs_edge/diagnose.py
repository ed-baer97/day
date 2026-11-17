"""Диагностика USB FTDI / порта / протокола Искра (только чтение)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agzs_edge.config import EdgeSettings, _resolve_preferred_port
from agzs_edge.iskra import IskraFrameError, build_test_command, parse_iskra_frame
from agzs_edge.serial_link import SerialAskaLink, list_available_serial_ports


@dataclass
class DiagnoseReport:
    ftdi_detected: bool = False
    serial_number: str = ""
    driver: str = ""
    port: str = ""
    access: str = "ERROR"
    protocol: str = "iskra_172"
    baudrate: int = 9600
    frame_validation: str = "UNKNOWN"
    checksum: str = "UNKNOWN"
    tx_bytes: int = 0
    rx_bytes: int = 0
    last_tx_hex: str = ""
    last_rx_hex: str = ""
    timeouts: int = 0
    invalid_frames: int = 0
    status: str = "UNKNOWN"
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "USB:",
            f"FTDI detected: {'YES' if self.ftdi_detected else 'NO'}",
            f"Serial: {self.serial_number or 'UNKNOWN'}",
            f"Driver: {self.driver or 'UNKNOWN'}",
            f"Port: {self.port or 'UNKNOWN'}",
            f"Access: {self.access}",
            "",
            "PROTOCOL:",
            f"Configured: {self.protocol}",
            f"Baudrate: {self.baudrate}",
            f"Frame validation: {self.frame_validation}",
            f"Checksum: {self.checksum}",
            "",
            "COMMUNICATION:",
            f"TX bytes: {self.tx_bytes}",
            f"RX bytes: {self.rx_bytes}",
            f"Last TX HEX: {self.last_tx_hex or '-'}",
            f"Last RX HEX: {self.last_rx_hex or '-'}",
            f"Timeouts: {self.timeouts}",
            f"Invalid frames: {self.invalid_frames}",
            "",
            "STATUS:",
            self.status,
        ]
        if self.notes:
            lines.append("")
            lines.append("NOTES:")
            lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines)


def resolve_preferred_port(configured: str) -> str:
    """Предпочитает стабильный /dev/serial/by-id/ для FTDI, если он есть."""
    return _resolve_preferred_port(configured)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=8)
    except Exception as exc:
        return f"ERR:{exc}"


def collect_usb_info(report: DiagnoseReport, port: str) -> None:
    lsusb = _run(["lsusb"])
    report.ftdi_detected = ("0403:6001" in lsusb) or ("FTDI" in lsusb.upper())
    mods = _run(["bash", "-lc", "lsmod | grep -E 'ftdi_sio|usbserial' || true"])
    report.driver = "ftdi_sio+usbserial" if "ftdi_sio" in mods else mods.strip() or "unknown"
    udev = _run(["udevadm", "info", "-q", "property", "-n", port])
    for line in udev.splitlines():
        if line.startswith("ID_SERIAL_SHORT="):
            report.serial_number = line.split("=", 1)[1].strip()
        if line.startswith("ID_USB_DRIVER="):
            report.driver = line.split("=", 1)[1].strip() or report.driver
    if not report.serial_number and "A5069RR4" in lsusb:
        report.serial_number = "A5069RR4"


def run_diagnose(settings: EdgeSettings, *, address: int = 1) -> DiagnoseReport:
    report = DiagnoseReport(
        protocol=getattr(settings, "protocol", "iskra_172"),
        baudrate=settings.serial_baudrate,
        checksum=settings.layout.checksum_mode.upper(),
    )
    port = resolve_preferred_port(settings.serial_port)
    report.port = port
    collect_usb_info(report, port if Path(port).exists() or port.startswith("/dev/") else "/dev/ttyUSB0")

    ports = list_available_serial_ports()
    if not any(p[0] == port or port in p[2] for p in ports) and not Path(port).exists():
        report.access = "ERROR"
        report.status = "DRIVER_ERROR"
        report.notes.append("Порт не найден в системе")
        return report

    # Офлайн-проверка кодека на эталонном кадре
    try:
        sample = build_test_command(address, checksum_mode=settings.layout.checksum_mode)
        # round-trip через эталонный ответ
        from agzs_edge.iskra import STATE_IDLE, build_test_response_frame

        resp = build_test_response_frame(
            address=address,
            state_code=STATE_IDLE,
            price_digits=7200,
            volume_ml=0,
            checksum_mode=settings.layout.checksum_mode,
        )
        parse_iskra_frame(resp, settings.layout)
        report.frame_validation = "OK"
        report.checksum = "OK"
        report.notes.append(f"Эталонный TX «Тест»: {sample.hex(' ').upper()}")
    except Exception as exc:
        report.frame_validation = "FAIL"
        report.checksum = "FAIL"
        report.notes.append(f"Ошибка офлайн-кодека: {exc}")

    link = SerialAskaLink(
        port=port,
        baudrate=settings.serial_baudrate,
        timeout_sec=max(settings.serial_timeout_sec, 1.5),
        layout=settings.layout,
        min_wait_sec=1.5,
    )
    try:
        res = link.poll_test(address)
        report.access = "OK" if res.error_message is None else "ERROR"
        report.tx_bytes = len(res.request_bytes)
        report.rx_bytes = len(res.response_bytes)
        report.last_tx_hex = res.request_bytes.hex(" ").upper()
        report.last_rx_hex = res.response_bytes.hex(" ").upper() if res.response_bytes else ""
        if res.error_message:
            report.status = "PORT_BUSY" if "busy" in res.error_message.lower() or "Permission" in res.error_message else "DRIVER_ERROR"
            report.notes.append(res.error_message)
        elif not res.has_response:
            report.timeouts = 1
            report.status = "NO_RESPONSE"
            report.notes.append(
                "TX ушёл, RX=0. Индикаторы АСКА не доказывают ответ колонки. "
                "Совместимость Искра 1.72 с прошивкой АСКА-02 07.2026 не подтверждена производителем."
            )
            report.notes.append(
                "Гипотеза (не доказательство): возможен PROTOCOL_MISMATCH_SUSPECTED — нужна спецификация АСКА-02."
            )
        else:
            try:
                parse_iskra_frame(res.response_bytes, settings.layout)
                report.status = "CONNECTED"
                report.frame_validation = "OK"
            except IskraFrameError as exc:
                report.invalid_frames = 1
                report.status = "PROTOCOL_MISMATCH_SUSPECTED"
                report.frame_validation = "FAIL"
                report.notes.append(str(exc))
    finally:
        link.close()

    # Не логируем токены
    if settings.device_token:
        report.notes.append("VPS token: present (скрыт)")
    else:
        report.notes.append("VPS token: missing")
    return report
