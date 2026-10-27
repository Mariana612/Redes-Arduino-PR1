import pytest

from redes_arduino import frame
from redes_arduino.frame import FrameError, FrameType
from redes_arduino.messages import (
    Abort,
    AbortReason,
    Ack,
    FileType,
    Fin,
    FinAck,
    FinStatus,
    Speed,
    Start,
    StartAck,
    StartStatus,
)

START = Start(0xDEADBEEF, 123_456, FileType.PNG, Speed.BPS_19200, 900, 6, True)


def test_start_layout_14_bytes() -> None:
    fr = START.to_frame()
    assert fr.type is FrameType.START
    assert fr.payload == bytes.fromhex("deadbeef 0001e240 03 02 0384 06 01")
    assert Start.from_payload(frame.decode(fr.encode()).payload) == START


@pytest.mark.parametrize(
    "bad",
    [
        bytes.fromhex("00000001 00000010 01 01 01f4 05 00"),
        bytes.fromhex("00000001 00000010 01 01 0100 04 00"),
        bytes.fromhex("00000001 00000010 04 01 01f4 04 00"),
        bytes.fromhex("00000001 00000010 01 03 01f4 04 00"),
        bytes.fromhex("00000001 00000010 01 01 01f4 04 02"),
        bytes(13),
    ],
)
def test_start_rejects_invalid(bad: bytes) -> None:
    with pytest.raises(FrameError):
        Start.from_payload(bad)


def test_speed_baud() -> None:
    assert Speed.BPS_9600.baud == 9600
    assert Speed.BPS_19200.baud == 19200


def test_start_ack_and_fin_ack() -> None:
    sa = StartAck(7, StartStatus.ACCEPTED)
    assert sa.to_frame().payload == b"\x00\x00\x00\x07\x00"
    assert StartAck.from_payload(sa.to_frame().payload) == sa
    fa = FinAck(7, FinStatus.HASH_MISMATCH)
    assert FinAck.from_payload(fa.to_frame().payload) == fa


def test_ack_uses_ack_field() -> None:
    fr = Ack(7, 12).to_frame()
    assert fr.type is FrameType.ACK and fr.seq == 0xFF and fr.ack == 12
    assert Ack.from_frame(frame.decode(fr.encode())) == Ack(7, 12)


def test_fin_36_bytes() -> None:
    fin = Fin(1, bytes(range(32)))
    assert len(fin.to_frame().payload) == 36
    assert Fin.from_payload(fin.to_frame().payload) == fin
    with pytest.raises(FrameError):
        Fin(1, b"corto").to_frame()


def test_abort() -> None:
    ab = Abort(9, AbortReason.MAX_RETRIES)
    assert Abort.from_payload(ab.to_frame().payload) == ab
    with pytest.raises(FrameError):
        Abort.from_payload(b"\x00\x00\x00\x09\x99")
