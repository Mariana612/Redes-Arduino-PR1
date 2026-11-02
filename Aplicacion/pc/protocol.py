"""Protocolo de enlace usado por endpoint.py.

Formato lógico (antes del byte stuffing):
    CONTROL | SEQ | ACK | LEN_H | LEN_L | PAYLOAD | CHECKSUM_H | CHECKSUM_L
La trama completa se delimita con 0x7E y escapa 0x7E/0x7D con 0x7D + XOR 0x20.
El checksum es suma de palabras de 16 bits en complemento a uno.
"""

FRAME_FLAG = 0x7E
FRAME_ESCAPE = 0x7D
FRAME_XOR = 0x20

TYPE_DATA = 0x01
TYPE_ACK = 0x02
TYPE_START = 0x03
TYPE_FIN = 0x04
TYPE_ABORT = 0x05
TYPE_START_ACK = 0x06
TYPE_FIN_ACK = 0x07
TYPE_HAMMING_STATS = 0x08

SEQ_CONTROL = 0xFF
ACK_NONE = 0xFF
MAX_PAYLOAD = 900


def checksum16(data: bytes) -> int:
    """Checksum Internet de 16 bits (suma en complemento a uno)."""
    if len(data) & 1:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _escape(data: bytes) -> bytes:
    out = bytearray()
    for value in data:
        if value in (FRAME_FLAG, FRAME_ESCAPE):
            out.extend((FRAME_ESCAPE, value ^ FRAME_XOR))
        else:
            out.append(value)
    return bytes(out)


def _unescape(data: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for value in data:
        if escaped:
            out.append(value ^ FRAME_XOR)
            escaped = False
        elif value == FRAME_ESCAPE:
            escaped = True
        else:
            out.append(value)
    if escaped:
        raise ValueError("escape incompleto al final de la trama")
    return bytes(out)


def build_frame(control: int, sequence: int = SEQ_CONTROL,
                ack: int = ACK_NONE, payload: bytes = b"") -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload)
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload demasiado grande: {len(payload)} > {MAX_PAYLOAD}")
    if not (0 <= control <= 0xFF and 0 <= sequence <= 0xFF and 0 <= ack <= 0xFF):
        raise ValueError("control, sequence y ack deben caber en un byte")

    length = len(payload)
    protected = bytes((control, sequence, ack, (length >> 8) & 0xFF, length & 0xFF)) + payload
    check = checksum16(protected)
    body = protected + check.to_bytes(2, "big")
    return bytes((FRAME_FLAG,)) + _escape(body) + bytes((FRAME_FLAG,))


def parse_frame(raw: bytes) -> dict:
    raw = bytes(raw)
    if len(raw) < 2 or raw[0] != FRAME_FLAG or raw[-1] != FRAME_FLAG:
        raise ValueError("faltan delimitadores 0x7E")
    body = _unescape(raw[1:-1])
    if len(body) < 7:
        raise ValueError("trama demasiado corta")

    control, sequence, ack, length_hi, length_lo = body[:5]
    length = (length_hi << 8) | length_lo
    expected = 5 + length + 2
    if length > MAX_PAYLOAD:
        raise ValueError(f"longitud declarada fuera de rango: {length}")
    if len(body) != expected:
        raise ValueError(f"longitud inválida: recibidos={len(body)}, esperados={expected}")

    protected = body[:-2]
    received_check = int.from_bytes(body[-2:], "big")
    calculated_check = checksum16(protected)
    if received_check != calculated_check:
        raise ValueError(
            f"checksum inválido: recibido=0x{received_check:04X}, calculado=0x{calculated_check:04X}"
        )

    return {
        "control": control,
        "sequence": sequence,
        "ack": ack,
        "payload": body[5:-2],
    }
