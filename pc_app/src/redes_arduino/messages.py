"""Cargas útiles de las tramas de control (START, START_ACK, ACK, FIN, FIN_ACK, ABORT).

Todos los enteros multibyte van en big-endian. Los códigos de estado distintos
de 0x00 marcados como "propuesta" no los fija el informe de la Etapa 1.
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Self

from .frame import Frame, FrameError, FrameType


class FileType(IntEnum):
    TXT = 0x01
    PDF = 0x02
    PNG = 0x03


class Speed(IntEnum):
    BPS_9600 = 0x01
    BPS_19200 = 0x02

    @property
    def baud(self) -> int:
        return 9600 if self is Speed.BPS_9600 else 19200


class StartStatus(IntEnum):
    ACCEPTED = 0x00
    INCOMPATIBLE_PARAMS = 0x01  # propuesta
    BUSY = 0x02  # propuesta


class FinStatus(IntEnum):
    OK = 0x00
    SIZE_MISMATCH = 0x01  # propuesta
    HASH_MISMATCH = 0x02  # propuesta


class AbortReason(IntEnum):
    USER = 0x01  # propuesta
    MAX_RETRIES = 0x02  # propuesta
    INTERNAL_ERROR = 0x03  # propuesta


PAYLOAD_SIZES = (500, 900)
WINDOW_SIZES = (4, 6, 8)


def _unpack(fmt: str, payload: bytes, name: str) -> tuple[Any, ...]:
    if len(payload) != struct.calcsize(fmt):
        raise FrameError(f"{name}: se esperaban {struct.calcsize(fmt)} bytes, hay {len(payload)}")
    return struct.unpack(fmt, payload)


def _enum[E: IntEnum](cls: type[E], value: int, name: str) -> E:
    try:
        return cls(value)
    except ValueError:
        raise FrameError(f"{name}: valor inválido {value}") from None


@dataclass(frozen=True)
class Start:
    FMT = ">IIBBHBB"  # 14 bytes
    transfer_id: int
    file_size: int
    file_type: FileType
    speed: Speed
    payload_size: int
    window: int
    hamming: bool

    def to_frame(self) -> Frame:
        payload = struct.pack(
            self.FMT,
            self.transfer_id,
            self.file_size,
            self.file_type,
            self.speed,
            self.payload_size,
            self.window,
            int(self.hamming),
        )
        return Frame.control(FrameType.START, payload)

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        tid, size, ftype, speed, psize, window, ham = _unpack(cls.FMT, payload, "START")
        if psize not in PAYLOAD_SIZES:
            raise FrameError(f"START: tamaño de carga inválido {psize}")
        if window not in WINDOW_SIZES:
            raise FrameError(f"START: ventana inválida {window}")
        if ham not in (0, 1):
            raise FrameError(f"START: modo Hamming inválido {ham}")
        return cls(
            int(tid),
            int(size),
            _enum(FileType, ftype, "START tipo"),
            _enum(Speed, speed, "START velocidad"),
            int(psize),
            int(window),
            ham == 1,
        )


@dataclass(frozen=True)
class StartAck:
    FMT = ">IB"
    transfer_id: int
    status: StartStatus

    def to_frame(self) -> Frame:
        return Frame.control(
            FrameType.START_ACK, struct.pack(self.FMT, self.transfer_id, self.status)
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        tid, status = _unpack(cls.FMT, payload, "START_ACK")
        return cls(int(tid), _enum(StartStatus, status, "START_ACK estado"))


@dataclass(frozen=True)
class Ack:
    FMT = ">I"
    transfer_id: int
    next_expected: int

    def to_frame(self) -> Frame:
        return Frame.ack_frame(self.next_expected, struct.pack(self.FMT, self.transfer_id))

    @classmethod
    def from_frame(cls, frame: Frame) -> Self:
        (tid,) = _unpack(cls.FMT, frame.payload, "ACK")
        return cls(int(tid), frame.ack)


@dataclass(frozen=True)
class Fin:
    FMT = ">I32s"  # 36 bytes
    transfer_id: int
    sha256: bytes

    def to_frame(self) -> Frame:
        if len(self.sha256) != 32:
            raise FrameError("FIN: el SHA-256 debe tener 32 bytes")
        return Frame.control(FrameType.FIN, struct.pack(self.FMT, self.transfer_id, self.sha256))

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        tid, digest = _unpack(cls.FMT, payload, "FIN")
        assert isinstance(digest, bytes)
        return cls(int(tid), digest)


@dataclass(frozen=True)
class FinAck:
    FMT = ">IB"
    transfer_id: int
    status: FinStatus

    def to_frame(self) -> Frame:
        return Frame.control(
            FrameType.FIN_ACK, struct.pack(self.FMT, self.transfer_id, self.status)
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        tid, status = _unpack(cls.FMT, payload, "FIN_ACK")
        return cls(int(tid), _enum(FinStatus, status, "FIN_ACK estado"))


@dataclass(frozen=True)
class Abort:
    FMT = ">IB"
    transfer_id: int
    reason: AbortReason

    def to_frame(self) -> Frame:
        return Frame.control(FrameType.ABORT, struct.pack(self.FMT, self.transfer_id, self.reason))

    @classmethod
    def from_payload(cls, payload: bytes) -> Self:
        tid, reason = _unpack(cls.FMT, payload, "ABORT")
        return cls(int(tid), _enum(AbortReason, reason, "ABORT causa"))
