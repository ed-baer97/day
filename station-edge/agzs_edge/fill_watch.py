"""Наблюдение одного налива. Только команда «Тест», без записи в базу и без команд колонке."""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agzs_edge.iskra import IskraFrameError, IskraTelemetryFrame, parse_iskra_frame
from agzs_edge.serial_link import AskaLink
from agzs_edge.tracker import CompletedDispense, PumpDispenseTracker


@dataclass
class FillSample:
    observed_at: datetime
    state_code: str
    state_name: str
    volume_ml: int
    price_kzt_per_liter: float
    error_code: str
    raw_hex: str


@dataclass
class FillWatchReport:
    address: int
    samples: list[FillSample] = field(default_factory=list)
    tracker_dispenses: list[CompletedDispense] = field(default_factory=list)
    raw_errors: int = 0
    empty_reads: int = 0

    @property
    def column_total_ml(self) -> int:
        if not self.samples:
            return 0
        return max(sample.volume_ml for sample in self.samples)

    @property
    def tracker_total_ml(self) -> int:
        return sum(item.dispensed_ml for item in self.tracker_dispenses)

    def render(self) -> str:
        lines = [
            f"Колонка {self.address}",
            f"Кадров: {len(self.samples)}, пустых чтений: {self.empty_reads}, битых кадров: {self.raw_errors}",
            f"Счётчик колонки, максимум: {self.column_total_ml} мл ({self.column_total_ml / 1000:.3f} л)",
            f"Закрытий учёта: {len(self.tracker_dispenses)}, сумма учёта: {self.tracker_total_ml} мл",
        ]
        if self.samples:
            first, last = self.samples[0], self.samples[-1]
            lines.append(
                f"Первый кадр: {first.state_code}/{first.state_name} {first.volume_ml} мл, цена {first.price_kzt_per_liter:.2f}"
            )
            lines.append(
                f"Последний кадр: {last.state_code}/{last.state_name} {last.volume_ml} мл, цена {last.price_kzt_per_liter:.2f}"
            )
        if len(self.tracker_dispenses) > 1 or (
            self.tracker_dispenses and self.tracker_total_ml != self.column_total_ml
        ):
            lines.append(
                "ВНИМАНИЕ: учёт разрезал один налив на несколько записей или сумма не совпала со счётчиком колонки. "
                "В литры брать счётчик колонки, записи учёта не складывать."
            )
            for item in self.tracker_dispenses:
                lines.append(f"  учёт: {item.dispensed_ml} мл, режим {item.mode}, состояние {item.final_state_code}")
        elif self.tracker_dispenses:
            lines.append("Учёт совпал со счётчиком колонки.")
        else:
            lines.append("Учёт заправку не закрыл. Итог только по максимальному счётчику колонки.")
        return "\n".join(lines)


def _record_frame(
    report: FillWatchReport,
    tracker: PumpDispenseTracker,
    frame: IskraTelemetryFrame,
) -> tuple[FillSample, bool]:
    sample = FillSample(
        observed_at=datetime.now(timezone.utc),
        state_code=frame.state_code,
        state_name=frame.state_name,
        volume_ml=frame.effective_volume_ml,
        price_kzt_per_liter=frame.price_kzt_per_liter,
        error_code=frame.error_code,
        raw_hex=frame.raw_hex,
    )
    changed = not report.samples or (
        report.samples[-1].state_code != sample.state_code
        or report.samples[-1].volume_ml != sample.volume_ml
    )
    report.samples.append(sample)
    closed = tracker.process_frame(frame)
    if closed is not None:
        report.tracker_dispenses.append(closed)
    return sample, changed


def _idle_expired(
    now: float,
    seen_dispensing: bool,
    last_dispensing_at: float | None,
    idle_seconds: float,
) -> bool:
    return (
        idle_seconds > 0
        and seen_dispensing
        and last_dispensing_at is not None
        and now - last_dispensing_at >= idle_seconds
    )


def consume_frames(address: int, frames: list[IskraTelemetryFrame]) -> FillWatchReport:
    """Прогоняет уже разобранные кадры через тот же трекер, что и боевая служба. Базу не трогает."""
    report = FillWatchReport(address=address)
    tracker = PumpDispenseTracker(station_code="AGZS-AKT-12")
    for frame in frames:
        if frame.address == address:
            _record_frame(report, tracker, frame)
    return report


def watch_fill(
    link: AskaLink,
    address: int,
    *,
    layout,
    max_seconds: float = 900.0,
    idle_seconds: float = 8.0,
    on_sample=None,
) -> FillWatchReport:
    """Читает команду «Тест», пока не истечёт max_seconds, не наступит тишина или не придёт сигнал остановки."""
    report = FillWatchReport(address=address)
    tracker = PumpDispenseTracker(station_code="AGZS-AKT-12")
    started = time.monotonic()
    last_dispensing_at: float | None = None
    seen_dispensing = False
    stop_requested = False

    def _request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_int = signal.signal(signal.SIGINT, _request_stop)
    previous_term = signal.signal(signal.SIGTERM, _request_stop)
    try:
        while not stop_requested and time.monotonic() - started < max_seconds:
            raw = link.poll_test(address)
            now = time.monotonic()
            if raw.error_message:
                raise RuntimeError(raw.error_message)
            if not raw.response_bytes:
                report.empty_reads += 1
                if _idle_expired(now, seen_dispensing, last_dispensing_at, idle_seconds):
                    break
                continue
            try:
                frame = parse_iskra_frame(raw.response_bytes, layout)
            except IskraFrameError:
                report.raw_errors += 1
                continue
            sample, changed = _record_frame(report, tracker, frame)
            if frame.is_dispensing:
                seen_dispensing = True
                last_dispensing_at = now
            elif _idle_expired(now, seen_dispensing, last_dispensing_at, idle_seconds):
                break
            if changed and on_sample is not None:
                on_sample(sample)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        link.close()
    return report
