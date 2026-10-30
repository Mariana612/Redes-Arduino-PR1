FRAME_FLAG = 0x7E
FRAME_ESCAPE = 0x7D
ESCAPE_XOR = 0x20

TYPE_DATA = 0x01
TYPE_ACK = 0x02
TYPE_START = 0x03
TYPE_FIN = 0x04
TYPE_ABORT = 0x05
TYPE_START_ACK = 0x06
TYPE_FIN_ACK = 0x07

SEQ_CONTROL = 0xFF
ACK_NONE = 0xFF

MAX_PAYLOAD = 900


def checksum16(data: bytes) -> int:
    """
    Checksum de complemento a uno de 16 bits.
    """

    # Si hay una cantidad impar de bytes,
    # se agrega 0x00 solamente para calcular el checksum.
    if len(data) % 2 != 0:
        data += b"\x00"

    total = 0

    for i in range(0, len(data), 2):
        word = (data[i] << 8) | data[i + 1]

        total += word

        # End-around carry
        total = (total & 0xFFFF) + (total >> 16)

    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)

    return (~total) & 0xFFFF


def escape_data(data: bytes) -> bytes:
    result = bytearray()

    for byte in data:
        if byte == FRAME_FLAG or byte == FRAME_ESCAPE:
            result.append(FRAME_ESCAPE)
            result.append(byte ^ ESCAPE_XOR)
        else:
            result.append(byte)

    return bytes(result)


def unescape_data(data: bytes) -> bytes:
    result = bytearray()

    i = 0

    while i < len(data):
        if data[i] == FRAME_ESCAPE:
            i += 1

            if i >= len(data):
                raise ValueError("Secuencia de escape incompleta")

            result.append(data[i] ^ ESCAPE_XOR)
        else:
            result.append(data[i])

        i += 1

    return bytes(result)


def build_frame(
    control: int,
    sequence: int,
    ack: int,
    payload: bytes = b""
) -> bytes:

    if len(payload) > MAX_PAYLOAD:
        raise ValueError(
            f"Payload demasiado grande: {len(payload)} bytes"
        )

    length = len(payload)

    # Longitud en 2 bytes, big-endian
    length_bytes = length.to_bytes(2, byteorder="big")

    # Datos protegidos por el checksum
    content = bytes([
        control,
        sequence,
        ack
    ]) + length_bytes + payload

    checksum = checksum16(content)

    checksum_bytes = checksum.to_bytes(
        2,
        byteorder="big"
    )

    # Se escapa todo excepto los delimitadores
    escaped = escape_data(
        content + checksum_bytes
    )

    return (
        bytes([FRAME_FLAG])
        + escaped
        + bytes([FRAME_FLAG])
    )


def parse_frame(raw_frame: bytes) -> dict:
    if len(raw_frame) < 2:
        raise ValueError("Trama demasiado corta")

    if raw_frame[0] != FRAME_FLAG:
        raise ValueError("Delimitador inicial invalido")

    if raw_frame[-1] != FRAME_FLAG:
        raise ValueError("Delimitador final invalido")

    # Quitar delimitadores
    escaped_content = raw_frame[1:-1]

    content = unescape_data(escaped_content)

    # 5 bytes de header + 2 de checksum
    if len(content) < 7:
        raise ValueError("Trama incompleta")

    control = content[0]
    sequence = content[1]
    ack = content[2]

    length = int.from_bytes(
        content[3:5],
        byteorder="big"
    )

    if length > MAX_PAYLOAD:
        raise ValueError("Longitud de payload invalida")

    expected_size = 5 + length + 2

    if len(content) != expected_size:
        raise ValueError(
            f"Longitud incorrecta: se esperaban "
            f"{expected_size} bytes y llegaron {len(content)}"
        )

    payload = content[5:5 + length]

    received_checksum = int.from_bytes(
        content[5 + length:7 + length],
        byteorder="big"
    )

    calculated_checksum = checksum16(
        content[:5 + length]
    )

    if received_checksum != calculated_checksum:
        raise ValueError(
            "Checksum invalido "
            f"(recibido=0x{received_checksum:04X}, "
            f"calculado=0x{calculated_checksum:04X})"
        )

    return {
        "control": control,
        "sequence": sequence,
        "ack": ack,
        "length": length,
        "payload": payload,
        "checksum": received_checksum
    }