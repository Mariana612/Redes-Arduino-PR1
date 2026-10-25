import pytest

from redes_arduino import framing, hamming

TRICKY = bytes([0x7E, 0x00, 0x7D, 0x7E, 0x7D, 0x5E, 0xFF])


def test_stuff_escapes_flag_and_esc() -> None:
    assert framing.stuff(b"\x7e\x7d\x01") == b"\x7d\x5e\x7d\x5d\x01"
    assert framing.unstuff(framing.stuff(TRICKY)) == TRICKY
    assert 0x7E not in framing.stuff(TRICKY)


@pytest.mark.parametrize("raw", [b"\x7d", b"\x7d\x01", b"\x01\x7e"])
def test_unstuff_rejects_invalid(raw: bytes) -> None:
    with pytest.raises(ValueError):
        framing.unstuff(raw)


@pytest.mark.parametrize("use_hamming", [True, False])
def test_encode_has_single_flags(use_hamming: bool) -> None:
    wire = framing.encode_physical(TRICKY, use_hamming)
    assert wire[0] == wire[-1] == 0x7E
    assert 0x7E not in wire[1:-1]


@pytest.mark.parametrize("use_hamming", [True, False])
def test_deframer_byte_by_byte_with_garbage(use_hamming: bool) -> None:
    bodies = [TRICKY, b"segunda", bytes(range(256))]
    stream = b"basura" + b"".join(framing.encode_physical(b, use_hamming) for b in bodies)
    d = framing.Deframer(use_hamming)
    frames = [f for i in range(len(stream)) for f in d.feed(stream[i : i + 1])]
    assert [f.body for f in frames] == bodies
    assert all(f.valid for f in frames)


def test_deframer_reports_hamming_correction() -> None:
    wire = bytearray(framing.encode_physical(b"\x41", True))
    wire[2] ^= 0x04  # 1 bit en el único bloque (no crea 0x7E/0x7D)
    (pf,) = framing.Deframer(True).feed(bytes(wire))
    assert pf.valid and pf.body == b"\x41"
    assert pf.stats is not None and pf.stats.corrected == 1


def test_deframer_marks_double_error_invalid() -> None:
    word = hamming.encode_byte(0x41) ^ 0b11  # 2 bits
    wire = b"\x7e" + framing.stuff(word.to_bytes(2, "big")) + b"\x7e"
    (pf,) = framing.Deframer(True).feed(wire)
    assert not pf.valid
    assert pf.reason == "error Hamming no corregible"


def test_deframer_odd_hamming_length_invalid() -> None:
    (pf,) = framing.Deframer(True).feed(b"\x7e\x01\x02\x03\x7e")
    assert not pf.valid


def test_deframer_overflow_then_recovers() -> None:
    d = framing.Deframer(False)
    junk = b"\x7e" + b"\x01" * (framing.MAX_RAW_LEN + 10)
    frames = list(d.feed(junk + framing.encode_physical(b"ok", False)))
    assert not frames[0].valid
    assert frames[0].reason == "trama demasiado larga"
    assert frames[1].body == b"ok"
