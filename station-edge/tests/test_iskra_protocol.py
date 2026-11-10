"""Тесты протокола Искра 1.72 (команда «Тест» код 4 и 23-байтный ответный кадр)."""

import pytest

from agzs_edge.config import FrameLayout
from agzs_edge.iskra import (
    EXPECTED_FRAME_LEN,
    SOH,
    STATE_DISPENSING,
    STATE_ERROR,
    IskraFrameError,
    build_test_command,
    build_test_response_frame,
    parse_iskra_frame,
    verify_frame_checksum,
)


def test_build_test_command_addresses_1_to_6() -> None:
    for addr in range(1, 7):
        cmd = build_test_command(addr)
        assert len(cmd) == 5
        assert cmd[0] == SOH
        assert cmd[1] == ord(str(addr))
        assert cmd[2] == ord("4")  # код 4 — команда «Тест»
        assert cmd[3] == 0x03


def test_build_test_command_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        build_test_command(0)
    with pytest.raises(ValueError):
        build_test_command(7)


def test_parse_valid_23_byte_iskra_frame() -> None:
    raw = build_test_response_frame(
        address=1,
        state_code=STATE_DISPENSING,
        error_code="00",
        price_digits=10500,  # 105.00 ₸/л
        volume_ml=12500,
        flags="01",
    )
    assert len(raw) == EXPECTED_FRAME_LEN
    assert raw[0] == 0x01
    assert verify_frame_checksum(raw)

    parsed = parse_iskra_frame(raw)
    assert parsed.address == 1
    assert parsed.command_code == ord("4")
    assert parsed.state_code == STATE_DISPENSING
    assert parsed.state_name == "DISPENSING"
    assert parsed.error_code == "00"
    assert parsed.price_raw == "010500"
    assert parsed.price_kzt_per_liter == 105.0
    assert parsed.volume_ml == 12500
    assert parsed.flags_raw == "01"
    assert not parsed.has_protocol_alarm


def test_parse_alarm_06_frame() -> None:
    raw = build_test_response_frame(
        address=2,
        state_code=STATE_ERROR,
        error_code="06",
        price_digits=10000,
        volume_ml=4300,
    )
    parsed = parse_iskra_frame(raw)
    assert parsed.address == 2
    assert parsed.error_code == "06"
    assert parsed.has_protocol_alarm


def test_parse_rejects_wrong_length_or_bad_checksum() -> None:
    raw = build_test_response_frame(address=1, volume_ml=5000)
    with pytest.raises(IskraFrameError, match="Неверная длина"):
        parse_iskra_frame(raw[:-1])

    corrupted = bytearray(raw)
    corrupted[-1] ^= 0xFF
    with pytest.raises(IskraFrameError, match="контрольная сумма"):
        parse_iskra_frame(bytes(corrupted))

    # В режиме checksum_mode='any' для стендовой диагностики
    layout_sum8 = FrameLayout(checksum_mode="sum8")
    raw_sum8 = build_test_response_frame(address=3, volume_ml=7700, checksum_mode="sum8")
    parsed = parse_iskra_frame(raw_sum8, layout_sum8)
    assert parsed.address == 3
    assert parsed.volume_ml == 7700
