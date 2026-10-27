import pytest

from redes_arduino import frame
from redes_arduino.frame import Frame, FrameError, FrameType


def test_data_layout() -> None:
    body = Frame.data(3, b"\x01\x02\x03").encode()
    assert body[:5] == bytes([0x01, 0x03, 0xFF, 0x00, 0x03])
    assert body[5:8] == b"\x01\x02\x03"
    assert len(body) == 5 + 3 + 2


@pytest.mark.parametrize(
    "fr",
    [
        Frame.data(0, b""),
        Frame.data(15, bytes(900)),
        Frame.ack_frame(7, b"\x00\x00\x00\x01"),
        Frame.control(FrameType.START, bytes(14)),
        Frame.control(FrameType.ABORT, b"\x00\x00\x00\x01\x01"),
    ],
)
def test_roundtrip(fr: Frame) -> None:
    assert frame.decode(fr.encode()) == fr


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": FrameType.DATA, "seq": 16},
        {"type": FrameType.DATA, "seq": 0, "ack": 1},
        {"type": FrameType.ACK, "ack": 16},
        {"type": FrameType.START, "seq": 0},
        {"type": FrameType.FIN, "ack": 0},
        {"type": FrameType.DATA, "seq": 0, "payload": bytes(901)},
    ],
)
def test_invalid_frames_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(FrameError):
        Frame(**kwargs)  # type: ignore[arg-type]


def test_decode_rejects_bad_checksum() -> None:
    body = bytearray(Frame.data(1, b"hola").encode())
    body[6] ^= 0x01
    with pytest.raises(FrameError, match="checksum"):
        frame.decode(bytes(body))


def test_decode_rejects_length_mismatch() -> None:
    body = Frame.data(1, b"hola").encode()
    with pytest.raises(FrameError, match="no coincide"):
        frame.decode(body[:-3] + body[-2:])


def test_decode_rejects_short_and_unknown() -> None:
    with pytest.raises(FrameError, match="corta"):
        frame.decode(b"\x01\x00")
    from redes_arduino.checksum import checksum

    covered = bytes([0x09, 0xFF, 0xFF, 0x00, 0x00])
    with pytest.raises(FrameError, match="desconocido"):
        frame.decode(covered + checksum(covered).to_bytes(2, "big"))


def test_decode_rejects_declared_length_over_max() -> None:
    from redes_arduino.checksum import checksum

    covered = bytes([0x01, 0x00, 0xFF]) + (901).to_bytes(2, "big") + bytes(901)
    with pytest.raises(FrameError, match="supera"):
        frame.decode(covered + checksum(covered).to_bytes(2, "big"))
