"""Trama lógica de la capa de enlace.

Cuerpo (sin delimitadores, que agrega la capa física):
    control(1) | secuencia(1) | ack(1) | longitud(2, BE) | carga(0..900) | checksum(2, BE)

El checksum cubre desde control hasta el final de la carga.
"""

from dataclasses import dataclass
from enum import IntEnum

from .checksum import checksum, verify

MAX_PAYLOAD = 900
HEADER_LEN = 5
CHECKSUM_LEN = 2
NO_SEQ = 0xFF  # tramas de control distintas de DATA
NO_ACK = 0xFF  # tramas DATA (sin piggybacking)
SEQ_MOD = 16


class FrameType(IntEnum):
    DATA = 0x01
    ACK = 0x02
    START = 0x03
    FIN = 0x04
    ABORT = 0x05
    START_ACK = 0x06
    FIN_ACK = 0x07


class FrameError(ValueError):
    """Trama inválida; el mensaje indica la razón."""


@dataclass(frozen=True)
class Frame:
    type: FrameType
    seq: int = NO_SEQ
    ack: int = NO_ACK
    payload: bytes = b""

    def __post_init__(self) -> None:
        if len(self.payload) > MAX_PAYLOAD:
            raise FrameError(f"carga de {len(self.payload)} bytes supera {MAX_PAYLOAD}")
        if self.type is FrameType.DATA:
            if not 0 <= self.seq < SEQ_MOD:
                raise FrameError(f"secuencia DATA fuera de rango: {self.seq}")
            if self.ack != NO_ACK:
                raise FrameError("DATA debe llevar ack 0xFF")
        else:
            if self.seq != NO_SEQ:
                raise FrameError(f"{self.type.name} debe llevar secuencia 0xFF")
            if self.type is FrameType.ACK and not 0 <= self.ack < SEQ_MOD:
                raise FrameError(f"ack fuera de rango: {self.ack}")
            if self.type is not FrameType.ACK and self.ack != NO_ACK:
                raise FrameError(f"{self.type.name} debe llevar ack 0xFF")

    @classmethod
    def data(cls, seq: int, payload: bytes) -> "Frame":
        return cls(FrameType.DATA, seq=seq, payload=payload)

    @classmethod
    def ack_frame(cls, next_expected: int, payload: bytes) -> "Frame":
        return cls(FrameType.ACK, ack=next_expected, payload=payload)

    @classmethod
    def control(cls, type: FrameType, payload: bytes) -> "Frame":
        return cls(type, payload=payload)

    def encode(self) -> bytes:
        head = bytes((self.type, self.seq, self.ack)) + len(self.payload).to_bytes(2, "big")
        covered = head + self.payload
        return covered + checksum(covered).to_bytes(2, "big")


def decode(body: bytes) -> Frame:
    """Interpreta un cuerpo recibido. Lanza FrameError si no es válido."""
    if len(body) < HEADER_LEN + CHECKSUM_LEN:
        raise FrameError(f"trama demasiado corta: {len(body)} bytes")
    length = int.from_bytes(body[3:5], "big")
    if length > MAX_PAYLOAD:
        raise FrameError(f"longitud declarada {length} supera {MAX_PAYLOAD}")
    if len(body) != HEADER_LEN + length + CHECKSUM_LEN:
        raise FrameError(
            f"longitud declarada {length} no coincide con {len(body) - HEADER_LEN - CHECKSUM_LEN}"
        )
    covered = body[:-CHECKSUM_LEN]
    if not verify(covered, int.from_bytes(body[-CHECKSUM_LEN:], "big")):
        raise FrameError("checksum inválido")
    try:
        ftype = FrameType(body[0])
    except ValueError:
        raise FrameError(f"tipo de trama desconocido: 0x{body[0]:02X}") from None
    return Frame(ftype, seq=body[1], ack=body[2], payload=body[HEADER_LEN:-CHECKSUM_LEN])
