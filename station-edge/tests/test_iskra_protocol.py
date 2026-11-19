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


def test_build_test_command_addresses_1_to_8() -> None:
    for addr in range(1, 9):
        cmd = build_test_command(addr)
        assert len(cmd) == EXPECTED_FRAME_LEN
        assert cmd[0] == SOH
        assert cmd[1:3] == f"{addr:02d}".encode("ascii")
        assert cmd[3] == ord("4")  # код 4 — команда «Тест»
        assert cmd[4] == 0x02
        assert cmd[21] == 0x03
        assert cmd[5:21] == b"0000000000000000"


def test_build_test_command_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        build_test_command(0)
    with pytest.raises(ValueError):
        build_test_command(9)


def test_parse_valid_23_byte_iskra_frame() -> None:
    raw = build_test_response_frame(
        address=1,
        state_code=STATE_DISPENSING,
        error_code="00",
        price_digits=10500,  # 105.00 ₸/л
        volume_ml=12500,
    )
    assert len(raw) == EXPECTED_FRAME_LEN
    assert raw[0] == 0x01
    assert raw[1:3] == b"01"
    assert raw[4] == 0x02
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


def test_parse_live_uzsg01_status_word() -> None:
    """Живой кадр УЗСГ-01: цена 72.00, объём 0, состояние 05, статус линии P|0x8E."""
    raw = bytes.fromhex("0130313402303037323030303030303030508E303503EA")
    assert verify_frame_checksum(raw)
    parsed = parse_iskra_frame(raw)
    assert parsed.address == 1
    assert parsed.command_code == ord("4")
    assert parsed.state_code == "05"
    assert parsed.state_name == "IDLE"
    assert parsed.price_raw == "007200"
    assert parsed.price_kzt_per_liter == 72.0
    assert parsed.volume_ml == 0
    assert parsed.error_code == "00"
    assert parsed.flags_raw == "P8E"
    assert not parsed.has_protocol_alarm


def test_parse_live_completed_frame_carries_fill_total_in_price_field() -> None:
    """Живой кадр 07 с уставкой 090000 и Volume=000000: объём равен 0, уставка 900 л, цена не искажается."""
    raw = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 50 91 30 37 03 FB")
    assert verify_frame_checksum(raw)
    parsed = parse_iskra_frame(raw)
    assert parsed.state_code == "07"
    assert parsed.price_raw == "090000"
    assert parsed.completed_volume_ml is None
    assert parsed.reported_volume_ml == 0
    assert parsed.preset_dose_ml == 900_000
    assert parsed.price_kzt_per_liter == 0.0
    assert parsed.volume_ml == 0


def test_parse_live_dispensing_frame_with_d0_flag_and_volume_in_price_field() -> None:
    """Живой кадр налива (03): статус D0 92 (0x50|0x80) не является ошибкой, а 090000 не искажает цену."""
    raw = bytes.fromhex("01 30 31 34 02 30 39 30 30 30 30 30 30 30 30 30 30 D0 92 30 33 03 7C")
    assert verify_frame_checksum(raw)
    parsed = parse_iskra_frame(raw)
    assert parsed.state_code == "03"
    assert parsed.error_code == "00"
    assert parsed.flags_raw == "P92"
    assert not parsed.has_protocol_alarm
    assert parsed.price_kzt_per_liter == 0.0
    assert parsed.volume_ml == 0


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


def test_parse_column_error_codes_in_sost_byte19_and_detailed_status() -> None:
    """Байт 19 Sost с кодами ошибок 01..04 (в т.ч. с установленным битом 7) корректно разбирается."""
    from agzs_edge.iskra import CMD_TEST_ASCII, ETX, STX, compute_bcc
    from agzs_edge.psu_controller import format_detailed_status

    for err_num, sost19 in [(1, 0x31), (2, 0x32), (3, 0xB3), (4, 0xB4)]:
        body = (
            b"01"
            + bytes([CMD_TEST_ASCII, STX])
            + b"007200"
            + b"001500"
            + bytes([0x50, 0x8E])
            + bytes([sost19, ord("7")])
            + bytes([ETX])
        )
        raw = bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])
        frame = parse_iskra_frame(raw)
        assert frame.state_code == "07"
        assert frame.column_error_code == err_num
        assert frame.has_protocol_alarm is True
        details = format_detailed_status(frame)
        assert f"Ошибка 0{err_num}" in details


def test_command_builders_and_bcc_validation() -> None:
    """Проверка валидации параметров в build_command_frame, build_set_dose_command, build_param_command, compute_bcc."""
    from agzs_edge.iskra import (
        CMD_TEST_ASCII,
        build_command_frame,
        build_param_command,
        build_set_dose_command,
        compute_bcc,
    )

    assert compute_bcc(b"ABC", "sum7") == (sum(b"ABC") & 0x7F)
    assert compute_bcc(b"ABC", "sum8") == (sum(b"ABC") & 0xFF)
    with pytest.raises(ValueError, match="режим"):
        compute_bcc(b"ABC", "crc16")

    with pytest.raises(ValueError):
        build_command_frame(1, 300)
    with pytest.raises(ValueError):
        build_command_frame(1, CMD_TEST_ASCII, status_ascii="0")
    with pytest.raises(ValueError):
        build_command_frame(1, CMD_TEST_ASCII, price_digits=1_000_000)
    with pytest.raises(ValueError):
        build_command_frame(1, CMD_TEST_ASCII, price_digits="BAD1234")

    with pytest.raises(ValueError):
        build_set_dose_command(1, 0)
    with pytest.raises(ValueError):
        build_set_dose_command(1, 1_000_000)

    cmd_custom = build_param_command(1, "123456", volume_digits=500)
    assert cmd_custom[5:11] == b"123456"
    with pytest.raises(ValueError, match="код параметра"):
        build_param_command(1, "9.99")
    for forbidden_code in ("0.1", "0.10", "0.13", "000010", "000013"):
        with pytest.raises(ValueError):
            build_param_command(1, forbidden_code)

    # Неверные маркеры SOH / STX / ETX / не-ASCII поля
    good = bytearray(build_test_response_frame(address=1, state_code="05", price_digits=7200, volume_ml=0))
    bad_soh = bytearray(good)
    bad_soh[0] = 0x00
    with pytest.raises(IskraFrameError, match="SOH"):
        parse_iskra_frame(bytes(bad_soh))

    bad_etx = bytearray(good)
    bad_etx[21] = 0x00
    with pytest.raises(IskraFrameError, match="ETX"):
        parse_iskra_frame(bytes(bad_etx))

    bad_stx = bytearray(good)
    bad_stx[4] = 0x00
    bad_stx[-1] = compute_bcc(bytes(bad_stx[1:22]), "xor")
    with pytest.raises(IskraFrameError, match="STX"):
        parse_iskra_frame(bytes(bad_stx))

    bad_addr = bytearray(good)
    bad_addr[1:3] = b"09"
    bad_addr[-1] = compute_bcc(bytes(bad_addr[1:22]), "xor")
    with pytest.raises(IskraFrameError, match="диапазона"):
        parse_iskra_frame(bytes(bad_addr))

    bad_price = bytearray(good)
    bad_price[5:11] = b"ABCDEF"
    bad_price[-1] = compute_bcc(bytes(bad_price[1:22]), "xor")
    with pytest.raises(IskraFrameError, match="цены"):
        parse_iskra_frame(bytes(bad_price))

    bad_vol = bytearray(good)
    bad_vol[11:17] = b"XYZ123"
    bad_vol[-1] = compute_bcc(bytes(bad_vol[1:22]), "xor")
    with pytest.raises(IskraFrameError, match="объёма"):
        parse_iskra_frame(bytes(bad_vol))


def test_v310_price_below_10_mass_mode_money_dose_and_byte17_status() -> None:
    """Цена < 10.00, режим кг/плотномера, доза в деньгах и байт 17 в диапазоне 0x31..0x35."""
    from agzs_edge.iskra import CMD_TEST_ASCII, ETX, STX, compute_bcc

    def _raw_frame(price: bytes, vol: bytes, b17: int, b18: int, b19: int, state_ch: str) -> bytes:
        body = (
            b"01"
            + bytes([CMD_TEST_ASCII, STX])
            + price
            + vol
            + bytes([b17, b18, b19, ord(state_ch), ETX])
        )
        return bytes([SOH]) + body + bytes([compute_bcc(body, "xor")])

    # 1. Цена < 10.00 (пример из РЭ УЗСГ-01: 6.70 руб/л -> 000670)
    low_price = parse_iskra_frame(_raw_frame(b"000670", b"000000", 0x50, 0x8A, 0x30, "5"))
    assert low_price.price_kzt_per_liter == pytest.approx(6.70)

    # 2. Режим килограммов/плотномера (байт 19: биты 7..6 = 0;1 -> 0x70 = 0x40|0x30)
    mass_frame = parse_iskra_frame(_raw_frame(b"000540", b"005400", 0xD1, 0x8F, 0x70, "3"))
    assert mass_frame.is_mass_mode is True
    assert mass_frame.price_kzt_per_liter == 0.0
    assert mass_frame.density_kg_per_l == pytest.approx(0.540)
    assert mass_frame.effective_volume_ml == 10_000

    # 3. Доза в деньгах (биты 0..4 байта 17 == 0x12)
    money_frame = parse_iskra_frame(_raw_frame(b"002150", b"000000", 0x52, 0x8A, 0x30, "1"))
    assert money_frame.dose_type_bits == 0x12
    assert money_frame.preset_dose_ml is None
    assert money_frame.preset_amount == pytest.approx(21.50)

    # 4. Байт 17 в диапазоне 0x31..0x35 (напр. 0x31) не является ASCII-ошибкой
    status_31 = parse_iskra_frame(_raw_frame(b"007200", b"000000", 0x31, 0x32, 0x30, "5"))
    assert status_31.error_code == "00"
    assert status_31.flags_raw == "P32"
    assert status_31.has_protocol_alarm is False
