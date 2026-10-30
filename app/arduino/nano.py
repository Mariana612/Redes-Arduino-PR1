import serial
import hashlib
from pathlib import Path

from protocol import (
    build_frame,
    parse_frame,
    FRAME_FLAG,
    TYPE_DATA,
    TYPE_ACK,
    TYPE_START,
    TYPE_START_ACK,
    TYPE_FIN,
    TYPE_FIN_ACK,
    ACK_NONE,
    SEQ_CONTROL
)


# ============================================================
# CONFIGURACION
# ============================================================

PORT = "/dev/ttyUSB0"

BAUD_RATE = 9600
SERIAL_TIMEOUT = 0.1

WINDOW_SIZE = 4
SEQUENCE_SPACE = 16

PAYLOAD_SIZE = 500

HAMMING_ENABLED = False

OUTPUT_DIRECTORY = "."


# ============================================================
# CODIGOS
# ============================================================

FILE_TYPE_TXT = 0x01
FILE_TYPE_PDF = 0x02
FILE_TYPE_PNG = 0x03

BAUD_CODE_9600 = 0x01
BAUD_CODE_19200 = 0x02

STATUS_OK = 0x00
STATUS_INVALID_PARAMETERS = 0x01
STATUS_SIZE_ERROR = 0x02
STATUS_HASH_ERROR = 0x03


# ============================================================
# RECEPCION DE TRAMAS
# ============================================================

class FrameReceiver:

    def __init__(self):

        self.buffer = bytearray()
        self.receiving = False

    def feed(self, byte):

        value = byte[0]

        if not self.receiving:

            if value == FRAME_FLAG:

                self.buffer.clear()
                self.buffer.append(value)

                self.receiving = True

            return None

        self.buffer.append(value)

        if value == FRAME_FLAG:

            try:

                frame = parse_frame(
                    bytes(self.buffer)
                )

            except ValueError as error:

                print(
                    f"Trama invalida: {error}"
                )

                frame = None

            self.buffer.clear()
            self.receiving = False

            return frame

        return None


# ============================================================
# BAUD CODE
# ============================================================

def get_local_baud_code():

    if BAUD_RATE == 9600:
        return BAUD_CODE_9600

    if BAUD_RATE == 19200:
        return BAUD_CODE_19200

    return None


# ============================================================
# EXTENSION
# ============================================================

def get_extension(file_type):

    if file_type == FILE_TYPE_TXT:
        return ".txt"

    if file_type == FILE_TYPE_PDF:
        return ".pdf"

    if file_type == FILE_TYPE_PNG:
        return ".png"

    return ".bin"


# ============================================================
# START_ACK
# ============================================================

def send_start_ack(
    ser,
    transfer_id,
    status
):

    payload = (
        transfer_id.to_bytes(
            4,
            byteorder="big"
        )
        +
        bytes([status])
    )

    frame = build_frame(
        control=TYPE_START_ACK,
        sequence=SEQ_CONTROL,
        ack=ACK_NONE,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print(
        f"TX START_ACK "
        f"status={status}"
    )


# ============================================================
# ACK
# ============================================================

def send_ack(
    ser,
    sequence,
    transfer_id
):

    payload = (
        transfer_id.to_bytes(
            4,
            byteorder="big"
        )
    )

    frame = build_frame(
        control=TYPE_ACK,
        sequence=SEQ_CONTROL,
        ack=sequence,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print(
        f"TX ACK {sequence}"
    )


# ============================================================
# FIN_ACK
# ============================================================

def send_fin_ack(
    ser,
    transfer_id,
    status
):

    payload = (
        transfer_id.to_bytes(
            4,
            byteorder="big"
        )
        +
        bytes([status])
    )

    frame = build_frame(
        control=TYPE_FIN_ACK,
        sequence=SEQ_CONTROL,
        ack=ACK_NONE,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print(
        f"TX FIN_ACK "
        f"status={status}"
    )


# ============================================================
# PARSE START
# ============================================================

def parse_start_payload(payload):

    if len(payload) != 14:

        raise ValueError(
            "START debe contener "
            "14 bytes"
        )

    transfer_id = int.from_bytes(
        payload[0:4],
        byteorder="big"
    )

    file_size = int.from_bytes(
        payload[4:8],
        byteorder="big"
    )

    file_type = payload[8]

    baud_code = payload[9]

    payload_size = int.from_bytes(
        payload[10:12],
        byteorder="big"
    )

    window_size = payload[12]

    hamming_mode = payload[13]

    return {
        "transfer_id": transfer_id,
        "file_size": file_size,
        "file_type": file_type,
        "baud_code": baud_code,
        "payload_size": payload_size,
        "window_size": window_size,
        "hamming_mode": hamming_mode
    }


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    try:

        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=SERIAL_TIMEOUT
        )

    except serial.SerialException as error:

        print(error)

        return

    receiver = FrameReceiver()

    session_active = False

    current_transfer_id = None
    expected_file_size = None
    current_file_type = None

    expected_sequence = 0

    received_data = bytearray()

    # Conservar resultado del último FIN
    # para poder responder si FIN_ACK se pierde.
    last_finished_id = None
    last_finish_status = None

    print("==============================")
    print("GO-BACK-N RECEIVER")
    print("==============================")

    print("Esperando START...")

    try:

        while True:

            byte = ser.read(1)

            if not byte:
                continue

            frame = receiver.feed(byte)

            if frame is None:
                continue

            control = frame["control"]

            # =================================================
            # START
            # =================================================

            if control == TYPE_START:

                print()
                print("RX START")

                try:

                    info = parse_start_payload(
                        frame["payload"]
                    )

                except ValueError as error:

                    print(error)

                    continue

                transfer_id = (
                    info["transfer_id"]
                )

                print(
                    f"Transfer ID: "
                    f"0x{transfer_id:08X}"
                )

                print(
                    f"Tamaño esperado: "
                    f"{info['file_size']} bytes"
                )

                print(
                    f"Payload: "
                    f"{info['payload_size']}"
                )

                print(
                    f"Ventana: "
                    f"{info['window_size']}"
                )

                print(
                    f"Hamming: "
                    f"{info['hamming_mode']}"
                )

                # -----------------------------------------
                # START REPETIDO
                # -----------------------------------------

                if (
                    session_active
                    and
                    transfer_id
                    == current_transfer_id
                ):

                    print(
                        "START repetido"
                    )

                    send_start_ack(
                        ser,
                        transfer_id,
                        STATUS_OK
                    )

                    continue

                # -----------------------------------------
                # VALIDAR PARAMETROS
                # -----------------------------------------

                parameters_ok = True

                if (
                    info["baud_code"]
                    != get_local_baud_code()
                ):
                    parameters_ok = False

                if (
                    info["payload_size"]
                    != PAYLOAD_SIZE
                ):
                    parameters_ok = False

                if (
                    info["window_size"]
                    != WINDOW_SIZE
                ):
                    parameters_ok = False

                expected_hamming = (
                    0x01
                    if HAMMING_ENABLED
                    else 0x00
                )

                if (
                    info["hamming_mode"]
                    != expected_hamming
                ):
                    parameters_ok = False

                if not parameters_ok:

                    print(
                        "Parametros incompatibles"
                    )

                    send_start_ack(
                        ser,
                        transfer_id,
                        STATUS_INVALID_PARAMETERS
                    )

                    continue

                # -----------------------------------------
                # CREAR SESION
                # -----------------------------------------

                current_transfer_id = (
                    transfer_id
                )

                expected_file_size = (
                    info["file_size"]
                )

                current_file_type = (
                    info["file_type"]
                )

                expected_sequence = 0

                received_data.clear()

                session_active = True

                send_start_ack(
                    ser,
                    transfer_id,
                    STATUS_OK
                )

                print()
                print("==============================")
                print("SESION ESTABLECIDA")
                print("==============================")

                print(
                    "Esperando seq=0"
                )

                continue

            # =================================================
            # FIN
            # =================================================

            if control == TYPE_FIN:

                payload = frame["payload"]

                if len(payload) != 36:

                    print(
                        "FIN con longitud invalida"
                    )

                    continue

                transfer_id = int.from_bytes(
                    payload[0:4],
                    byteorder="big"
                )

                received_sha256 = (
                    payload[4:36]
                )

                print()
                print(
                    f"RX FIN "
                    f"id=0x{transfer_id:08X}"
                )

                # -----------------------------------------
                # FIN REPETIDO
                # -----------------------------------------

                if (
                    not session_active
                    and
                    transfer_id
                    == last_finished_id
                ):

                    print(
                        "FIN repetido"
                    )

                    send_fin_ack(
                        ser,
                        transfer_id,
                        last_finish_status
                    )

                    continue

                # -----------------------------------------
                # VALIDAR SESION
                # -----------------------------------------

                if (
                    not session_active
                    or
                    transfer_id
                    != current_transfer_id
                ):

                    print(
                        "FIN no corresponde "
                        "a la sesion activa"
                    )

                    continue

                # -----------------------------------------
                # VALIDAR TAMAÑO
                # -----------------------------------------

                if (
                    len(received_data)
                    != expected_file_size
                ):

                    status = (
                        STATUS_SIZE_ERROR
                    )

                    print(
                        "ERROR DE TAMAÑO"
                    )

                    print(
                        f"Esperado: "
                        f"{expected_file_size}"
                    )

                    print(
                        f"Recibido: "
                        f"{len(received_data)}"
                    )

                else:

                    calculated_sha256 = (
                        hashlib.sha256(
                            received_data
                        ).digest()
                    )

                    print(
                        "SHA esperado: "
                        f"{received_sha256.hex()}"
                    )

                    print(
                        "SHA calculado: "
                        f"{calculated_sha256.hex()}"
                    )

                    if (
                        calculated_sha256
                        != received_sha256
                    ):

                        status = (
                            STATUS_HASH_ERROR
                        )

                        print(
                            "ERROR SHA-256"
                        )

                    else:

                        status = STATUS_OK

                # -----------------------------------------
                # GUARDAR SOLO SI TODO ES CORRECTO
                # -----------------------------------------

                if status == STATUS_OK:

                    extension = get_extension(
                        current_file_type
                    )

                    output_file = (
                        Path(
                            OUTPUT_DIRECTORY
                        )
                        /
                        (
                            "archivo_recibido"
                            + extension
                        )
                    )

                    try:

                        with open(
                            output_file,
                            "wb"
                        ) as file:

                            file.write(
                                received_data
                            )

                        print()
                        print("==============================")
                        print("ARCHIVO VERIFICADO")
                        print("==============================")

                        print(
                            f"Guardado: "
                            f"{output_file}"
                        )

                        print(
                            f"Bytes: "
                            f"{len(received_data)}"
                        )

                        print(
                            "SHA-256: CORRECTO"
                        )

                    except OSError as error:

                        print(error)

                        status = (
                            STATUS_HASH_ERROR
                        )

                # -----------------------------------------
                # RECORDAR RESULTADO
                # -----------------------------------------

                last_finished_id = (
                    current_transfer_id
                )

                last_finish_status = (
                    status
                )

                send_fin_ack(
                    ser,
                    current_transfer_id,
                    status
                )

                session_active = False

                current_transfer_id = None

                print()
                print(
                    "Esperando START..."
                )

                continue

            # =================================================
            # DATA SIN SESION
            # =================================================

            if not session_active:

                if control == TYPE_DATA:

                    print(
                        "DATA ignorada: "
                        "sin sesion activa"
                    )

                continue

            # =================================================
            # DATA
            # =================================================

            if control != TYPE_DATA:
                continue

            sequence = frame["sequence"]

            print()
            print(
                f"RX DATA seq={sequence}"
            )

            # ---------------------------------------------
            # TRAMA ESPERADA
            # ---------------------------------------------

            if (
                sequence
                == expected_sequence
            ):

                payload = (
                    frame["payload"]
                )

                received_data.extend(
                    payload
                )

                print(
                    f"ACEPTADA "
                    f"seq={sequence} "
                    f"bytes={len(payload)} "
                    f"total="
                    f"{len(received_data)}"
                )

                send_ack(
                    ser,
                    sequence,
                    current_transfer_id
                )

                expected_sequence = (
                    expected_sequence + 1
                ) % SEQUENCE_SPACE

                print(
                    f"Ahora esperando "
                    f"seq="
                    f"{expected_sequence}"
                )

            # ---------------------------------------------
            # FUERA DE ORDEN
            # ---------------------------------------------

            else:

                print(
                    f"DESCARTADA "
                    f"seq={sequence}"
                )

                print(
                    f"Se esperaba "
                    f"{expected_sequence}"
                )

                last_valid = (
                    expected_sequence - 1
                ) % SEQUENCE_SPACE

                send_ack(
                    ser,
                    last_valid,
                    current_transfer_id
                )

    except KeyboardInterrupt:

        print(
            "\nRecepcion detenida"
        )

    finally:

        ser.close()


if __name__ == "__main__":
    main()