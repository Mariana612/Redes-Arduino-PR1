import time

import serial

FLAG = 0x7E
MAX_FRAME_LEN = 4098


def exchange_frame(frame: bytes, port: str, baud: int, timeout: float) -> bytes:
    """Envía una trama física y lee una respuesta delimitada por 0x7E."""
    if not frame:
        raise ValueError("la trama a enviar no puede estar vacía")

    deadline = time.monotonic() + timeout
    with serial.Serial(
        port=port,
        baudrate=baud,
        timeout=timeout,
        write_timeout=timeout,
    ) as serial_port:
        written = serial_port.write(frame)
        if written != len(frame):
            raise serial.SerialTimeoutException(
                f"envío incompleto: {written} de {len(frame)} bytes"
            )
        serial_port.flush()

        response = bytearray()
        started = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"sin respuesta serial en el puerto {port}")
            serial_port.timeout = remaining
            chunk = serial_port.read(1)
            if not chunk:
                raise TimeoutError(f"sin respuesta serial en el puerto {port}")

            byte = chunk[0]
            if not started:
                if byte == FLAG:
                    response.append(byte)
                    started = True
                continue

            response.append(byte)
            if len(response) > MAX_FRAME_LEN:
                raise ValueError("la trama serial recibida excede el tamaño máximo")
            if byte == FLAG:
                if len(response) > 2:
                    return bytes(response)
                response.clear()
                started = False
