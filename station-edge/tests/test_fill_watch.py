"""Офлайн-проверка наблюдения налива: счётчик колонки и разрезание учётом."""

from agzs_edge.fill_watch import consume_frames
from agzs_edge.iskra import STATE_COMPLETED, STATE_DISPENSING, build_test_response_frame, parse_iskra_frame


def _frame(volume_ml: int, state: str):
    raw = build_test_response_frame(
        address=1,
        state_code=state,
        price_digits=7000,
        volume_ml=volume_ml,
    )
    return parse_iskra_frame(raw)


def test_one_rising_fill_matches_tracker() -> None:
    frames = [_frame(ml, STATE_DISPENSING) for ml in (410, 530, 650, 7460)]
    frames.append(_frame(7460, STATE_COMPLETED))
    report = consume_frames(1, frames)
    assert report.column_total_ml == 7460
    assert report.tracker_total_ml == 7460
    assert len(report.tracker_dispenses) == 1


def test_mid_fill_completed_frame_is_reported_separately() -> None:
    """Краткое состояние 07 посреди растущего счётчика не должно скрывать итог колонки."""
    frames = [_frame(ml, STATE_DISPENSING) for ml in (410, 530, 4740)]
    frames.append(_frame(4740, STATE_COMPLETED))
    frames.extend(_frame(ml, STATE_DISPENSING) for ml in (5200, 6000, 7460))
    frames.append(_frame(7460, STATE_COMPLETED))
    report = consume_frames(1, frames)
    assert report.column_total_ml == 7460
    assert len(report.tracker_dispenses) == 2
    assert [item.dispensed_ml for item in report.tracker_dispenses] == [4740, 2720]
    assert report.tracker_total_ml == report.column_total_ml
    text = report.render()
    assert "7460 мл" in text
    assert "не складывать" in text


def test_watch_fill_handles_empty_corrupted_callback_and_idle_stop(monkeypatch) -> None:
    """watch_fill учитывает пустые/битые кадры, вызывает on_sample, останавливается по idle_seconds и ловит ошибки."""
    import pytest

    from agzs_edge.config import FrameLayout
    from agzs_edge.fill_watch import watch_fill
    from agzs_edge.iskra import STATE_COMPLETED, STATE_IDLE, build_test_command
    from agzs_edge.serial_link import PollRawResult

    seq = [
        PollRawResult(1, build_test_command(1), b""),
        PollRawResult(1, build_test_command(1), b"\x01BAD"),
        PollRawResult(1, build_test_command(1), build_test_response_frame(address=1, state_code=STATE_IDLE, volume_ml=0)),
        PollRawResult(1, build_test_command(1), build_test_response_frame(address=1, state_code=STATE_DISPENSING, volume_ml=1200)),
        PollRawResult(1, build_test_command(1), build_test_response_frame(address=1, state_code=STATE_DISPENSING, volume_ml=3400)),
        PollRawResult(1, build_test_command(1), build_test_response_frame(address=1, state_code=STATE_COMPLETED, volume_ml=3400)),
        PollRawResult(1, build_test_command(1), b""),
    ]

    class _StubLink:
        def __init__(self, items) -> None:
            self.items = list(items)
            self.closed = False

        def open(self) -> None:
            return

        def close(self) -> None:
            self.closed = True

        def poll_test(self, address: int, *, checksum_mode: str | None = None):
            return self.items.pop(0) if self.items else PollRawResult(address, b"", b"")

    # Имитируем рост monotonic на 3 секунды за каждый вызов, чтобы STATE_COMPLETED вызвал on_sample,
    # а следующий пустой ответ сработал по idle_seconds=8.0
    ticks = iter([float(i * 3) for i in range(50)])
    monkeypatch.setattr("agzs_edge.fill_watch.time.monotonic", lambda: next(ticks))

    seen_samples = []
    link = _StubLink(seq)
    report = watch_fill(
        link,
        1,
        layout=FrameLayout(),
        max_seconds=200.0,
        idle_seconds=8.0,
        on_sample=seen_samples.append,
    )
    assert link.closed is True
    assert report.empty_reads >= 1
    assert report.raw_errors == 1
    assert report.column_total_ml == 3400
    assert report.tracker_total_ml == 3400
    assert len(seen_samples) == 4
    assert "Учёт совпал со счётчиком колонки" in report.render()

    # Ошибка COM-порта приводит к RuntimeError
    err_link = _StubLink([PollRawResult(1, b"", b"", error_message="port disconnected")])
    with pytest.raises(RuntimeError, match="port disconnected"):
        watch_fill(err_link, 1, layout=FrameLayout(), max_seconds=10.0, idle_seconds=2.0)
    assert err_link.closed is True
