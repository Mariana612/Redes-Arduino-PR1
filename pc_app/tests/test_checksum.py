from redes_arduino.checksum import checksum, verify


def test_rfc1071_example() -> None:
    # Ejemplo de RFC 1071 sección 3: suma = 0xDDF2 -> checksum = 0x220D
    data = bytes.fromhex("0001f203f4f5f6f7")
    assert checksum(data) == 0x220D
    assert verify(data, 0x220D)


def test_empty_and_zero() -> None:
    assert checksum(b"") == 0xFFFF
    assert checksum(b"\x00\x00") == 0xFFFF


def test_odd_length_pads_with_zero() -> None:
    assert checksum(b"\x12\x34\x56") == checksum(b"\x12\x34\x56\x00")
    assert verify(b"\x12\x34\x56", checksum(b"\x12\x34\x56"))


def test_carry_wraps_around() -> None:
    assert checksum(b"\xff\xff\x00\x01") == 0xFFFE


def test_detects_altered_byte() -> None:
    data = bytearray(b"hola arduino uno y nano")
    cs = checksum(bytes(data))
    data[4] ^= 0x10
    assert not verify(bytes(data), cs)


def test_wrong_checksum_rejected() -> None:
    data = b"abc"
    assert not verify(data, checksum(data) ^ 0x0001)
