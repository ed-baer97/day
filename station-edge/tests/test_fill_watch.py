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
    assert report.tracker_total_ml != report.column_total_ml
    text = report.render()
    assert "7460 мл" in text
    assert "не складывать" in text
