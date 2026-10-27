"""Capa de red: segmentación en paquetes y verificación del archivo completo."""

import hashlib
from collections.abc import Iterable

from .messages import PAYLOAD_SIZES


def split(data: bytes, size: int) -> list[bytes]:
    """Divide en paquetes de `size` bytes; solo el último puede ser más corto."""
    if size not in PAYLOAD_SIZES:
        raise ValueError(f"tamaño de paquete inválido: {size} (use {PAYLOAD_SIZES})")
    return [data[i : i + size] for i in range(0, len(data), size)]


def reassemble(packets: Iterable[bytes]) -> bytes:
    return b"".join(packets)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
