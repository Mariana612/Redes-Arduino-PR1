"""Hamming extendido (13,8) SECDED de la capa física.

Distribución de bits (paridad par):
    - posiciones 1, 2, 4, 8  -> paridad Hamming
    - posiciones 3, 5, 6, 7, 9, 10, 11, 12 -> datos d0..d7 (d0 = LSB del byte)
    - posición 13 -> paridad global

La posición p se guarda en el bit (p - 1) de una palabra de 16 bits que viaja
como 2 bytes en orden big-endian. Los bits 13..15 de la palabra van en cero.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

DATA_POSITIONS = (3, 5, 6, 7, 9, 10, 11, 12)
PARITY_POSITIONS = (1, 2, 4, 8)
GLOBAL_POSITION = 13


class Status(Enum):
    OK = "ok"
    CORRECTED = "corrected"  # un bit erróneo en posiciones 1..12, corregido
    GLOBAL_PARITY_FIXED = "global_parity_fixed"  # solo falló el bit 13
    DOUBLE_ERROR = "double_error"  # no corregible


def _bit(word: int, pos: int) -> int:
    return (word >> (pos - 1)) & 1


def encode_byte(value: int) -> int:
    """Codifica un byte en una palabra de 13 bits."""
    if not 0 <= value <= 0xFF:
        raise ValueError(f"byte fuera de rango: {value}")
    word = 0
    for i, pos in enumerate(DATA_POSITIONS):
        if (value >> i) & 1:
            word |= 1 << (pos - 1)
    for p in PARITY_POSITIONS:
        parity = 0
        for pos in range(1, 13):
            if pos & p:
                parity ^= _bit(word, pos)
        word |= parity << (p - 1)
    if bin(word).count("1") % 2:
        word |= 1 << (GLOBAL_POSITION - 1)
    return word


def decode_word(word: int) -> tuple[int, Status]:
    """Decodifica una palabra de 13 bits. Devuelve (byte, estado)."""
    word &= 0x1FFF
    syndrome = 0
    for pos in range(1, 13):
        if _bit(word, pos):
            syndrome ^= pos
    global_ok = bin(word).count("1") % 2 == 0

    if syndrome == 0 and global_ok:
        status = Status.OK
    elif syndrome == 0:
        status = Status.GLOBAL_PARITY_FIXED
    elif not global_ok and syndrome <= 12:
        word ^= 1 << (syndrome - 1)
        status = Status.CORRECTED
    else:
        # síndrome != 0 con paridad global correcta, o síndrome imposible (13..15)
        status = Status.DOUBLE_ERROR

    value = 0
    for i, pos in enumerate(DATA_POSITIONS):
        value |= _bit(word, pos) << i
    return value, status


def encode_bytes(data: bytes) -> bytes:
    """Codifica cada byte en 2 bytes (big-endian)."""
    out = bytearray()
    for b in data:
        out += encode_byte(b).to_bytes(2, "big")
    return bytes(out)


@dataclass
class DecodeStats:
    blocks: int = 0
    corrected: int = 0  # incluye GLOBAL_PARITY_FIXED
    uncorrectable: int = 0
    error_offsets: list[int] = field(default_factory=list)  # índice de bloques no corregibles

    def merge(self, other: "DecodeStats") -> None:
        offset = self.blocks
        self.blocks += other.blocks
        self.corrected += other.corrected
        self.uncorrectable += other.uncorrectable
        self.error_offsets += [offset + i for i in other.error_offsets]


def decode_bytes(data: bytes) -> tuple[bytes, DecodeStats]:
    """Decodifica pares de bytes. Lanza ValueError si la longitud es impar."""
    if len(data) % 2:
        raise ValueError("la longitud codificada debe ser par")
    out = bytearray()
    stats = DecodeStats()
    for i in range(0, len(data), 2):
        value, status = decode_word(int.from_bytes(data[i : i + 2], "big"))
        out.append(value)
        stats.blocks += 1
        if status in (Status.CORRECTED, Status.GLOBAL_PARITY_FIXED):
            stats.corrected += 1
        elif status is Status.DOUBLE_ERROR:
            stats.uncorrectable += 1
            stats.error_offsets.append(i // 2)
    return bytes(out), stats


def table(values: Iterable[int] = range(256)) -> str:
    """Tabla 'byte -> palabra' para comparar con la implementación del Arduino."""
    return "\n".join(f"0x{v:02X} -> 0x{encode_byte(v):04X}" for v in values)
