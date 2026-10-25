"""Checksum de 16 bits con complemento a uno (estilo Internet, RFC 1071)."""


def _ones_sum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"  # relleno solo para el cálculo
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return total


def checksum(data: bytes) -> int:
    """Checksum a colocar en la trama."""
    return ~_ones_sum(data) & 0xFFFF


def verify(data: bytes, received: int) -> bool:
    """True si `received` es el checksum correcto de `data`."""
    if len(data) % 2:
        data += b"\x00"
    return _ones_sum(data + received.to_bytes(2, "big")) == 0xFFFF
