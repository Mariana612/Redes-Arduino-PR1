"""Delimitación y escape de la capa física.

Flujo de envío:   cuerpo -> (Hamming opcional) -> escape -> 0x7E + ... + 0x7E
Flujo de recepción: el inverso, con `Deframer` procesando bytes a medida que llegan.

Los delimitadores 0x7E viajan sin Hamming. Cualquier 0x7E o 0x7D interno se
envía como 0x7D seguido del byte XOR 0x20.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from . import hamming

FLAG = 0x7E
ESC = 0x7D
ESC_XOR = 0x20
# Trama máxima: 908 bytes de cuerpo -> 1816 con Hamming -> hasta 3632 con escapes.
MAX_RAW_LEN = 4096


def stuff(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in (FLAG, ESC):
            out += bytes((ESC, b ^ ESC_XOR))
        else:
            out.append(b)
    return bytes(out)


def unstuff(data: bytes) -> bytes:
    """Lanza ValueError si hay una secuencia de escape inválida."""
    out = bytearray()
    it = iter(data)
    for b in it:
        if b == FLAG:
            raise ValueError("0x7E sin escapar dentro de la trama")
        if b == ESC:
            nxt = next(it, None)
            if nxt is None:
                raise ValueError("escape al final de la trama")
            b = nxt ^ ESC_XOR
            if b not in (FLAG, ESC):
                raise ValueError(f"escape inválido: 0x7D 0x{nxt:02X}")
        out.append(b)
    return bytes(out)


def encode_physical(body: bytes, use_hamming: bool) -> bytes:
    """Bytes que el Arduino emisor pone en el cable para un cuerpo de trama."""
    coded = hamming.encode_bytes(body) if use_hamming else body
    return bytes((FLAG,)) + stuff(coded) + bytes((FLAG,))


@dataclass
class PhysicalFrame:
    body: bytes
    valid: bool
    stats: hamming.DecodeStats | None = None  # None si no se usa Hamming
    reason: str | None = None


def decode_physical(raw: bytes, use_hamming: bool) -> PhysicalFrame:
    """Decodifica el contenido entre dos delimitadores (sin incluirlos)."""
    try:
        coded = unstuff(raw)
    except ValueError as exc:
        return PhysicalFrame(b"", False, reason=str(exc))
    if not use_hamming:
        return PhysicalFrame(coded, True)
    if len(coded) % 2:
        return PhysicalFrame(b"", False, reason="longitud Hamming impar")
    body, stats = hamming.decode_bytes(coded)
    if stats.uncorrectable:
        return PhysicalFrame(body, False, stats, "error Hamming no corregible")
    return PhysicalFrame(body, True, stats)


class Deframer:
    """Arma tramas a partir de un flujo de bytes recibidos en trozos arbitrarios.

    Cada 0x7E es un límite: cierra la trama en curso (si no está vacía) y abre
    la siguiente. Los bytes previos al primer 0x7E se descartan.
    """

    def __init__(self, use_hamming: bool) -> None:
        self.use_hamming = use_hamming
        self._buf = bytearray()
        self._synced = False
        self._overflow = False

    def feed(self, data: bytes) -> Iterator[PhysicalFrame]:
        for b in data:
            if b == FLAG:
                if self._overflow:
                    yield PhysicalFrame(b"", False, reason="trama demasiado larga")
                elif self._synced and self._buf:
                    yield decode_physical(bytes(self._buf), self.use_hamming)
                self._buf.clear()
                self._synced = True
                self._overflow = False
            elif self._synced and not self._overflow:
                self._buf.append(b)
                if len(self._buf) > MAX_RAW_LEN:
                    self._overflow = True
                    self._buf.clear()
