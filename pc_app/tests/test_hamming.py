from itertools import combinations

import pytest

from redes_arduino import hamming
from redes_arduino.hamming import Status


@pytest.mark.parametrize("value", range(256))
def test_roundtrip(value: int) -> None:
    word = hamming.encode_byte(value)
    assert word < 1 << 13
    assert hamming.decode_word(word) == (value, Status.OK)


def test_known_vectors() -> None:
    assert hamming.encode_byte(0x00) == 0x0000
    assert hamming.encode_byte(0x01) == 0b1_0000_0000_0111


@pytest.mark.parametrize("value", range(256))
def test_single_bit_errors_are_corrected(value: int) -> None:
    word = hamming.encode_byte(value)
    for pos in range(1, 14):
        decoded, status = hamming.decode_word(word ^ (1 << (pos - 1)))
        assert decoded == value
        expected = Status.GLOBAL_PARITY_FIXED if pos == 13 else Status.CORRECTED
        assert status is expected


@pytest.mark.parametrize("value", [0x00, 0x5A, 0xA5, 0xFF, 0x7E, 0x7D])
def test_double_bit_errors_are_detected(value: int) -> None:
    word = hamming.encode_byte(value)
    for a, b in combinations(range(13), 2):
        _, status = hamming.decode_word(word ^ (1 << a) ^ (1 << b))
        assert status is Status.DOUBLE_ERROR


def test_encode_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        hamming.encode_byte(256)


def test_bytes_roundtrip_and_stats() -> None:
    data = bytes(range(256))
    coded = bytearray(hamming.encode_bytes(data))
    assert len(coded) == 512
    coded[1] ^= 0x01
    coded[11] ^= 0x03
    decoded, stats = hamming.decode_bytes(bytes(coded))
    assert stats.blocks == 256
    assert stats.corrected == 1
    assert stats.uncorrectable == 1
    assert stats.error_offsets == [5]
    assert decoded[0] == 0


def test_decode_odd_length() -> None:
    with pytest.raises(ValueError):
        hamming.decode_bytes(b"\x00")


def test_table_has_256_lines() -> None:
    assert len(hamming.table().splitlines()) == 256
