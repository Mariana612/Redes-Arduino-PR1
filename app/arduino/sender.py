import serial
import time
import hashlib
import secrets
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

PORT = "/dev/cu.usbserial-DA01LAZ1"

BAUD_RATE = 9600
SERIAL_TIMEOUT = 0.1

MAX_RETRIES = 5

WINDOW_SIZE = 4
SEQUENCE_SPACE = 16

TIMEOUT = 2.0

FILE_PATH = "test_files/test.txt"

PAYLOAD_SIZE = 500

HAMMING_ENABLED = False


# ============================================================
# CODIGOS DEL PROTOCOLO
# ============================================================

FILE_TYPE_TXT = 0x01
FILE_TYPE_PDF = 0x02
FILE_TYPE_PNG = 0x03

BAUD_CODE_9600 = 0x01
BAUD_CODE_19200 = 0x02

STATUS_OK = 0x00


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
                    f"Trama recibida invalida: {error}"
                )

                frame = None

            self.buffer.clear()
            self.receiving = False

            return frame

        return None


# ============================================================
# TIPO DE ARCHIVO
# ============================================================

def get_file_type(path):

    extension = Path(path).suffix.lower()

    if extension == ".txt":
        return FILE_TYPE_TXT

    if extension == ".pdf":
        return FILE_TYPE_PDF

    if extension == ".png":
        return FILE_TYPE_PNG

    raise ValueError(
        f"Tipo de archivo no soportado: {extension}"
    )


# ============================================================
# CODIGO BAUD
# ============================================================

def get_baud_code():

    if BAUD_RATE == 9600:
        return BAUD_CODE_9600

    if BAUD_RATE == 19200:
        return BAUD_CODE_19200

    raise ValueError(
        f"Baud rate no soportado: {BAUD_RATE}"
    )


# ============================================================
# CARGAR ARCHIVO
# ============================================================

def load_file(path):

    with open(path, "rb") as file:

        data = file.read()

    payloads = [
        data[i:i + PAYLOAD_SIZE]
        for i in range(
            0,
            len(data),
            PAYLOAD_SIZE
        )
    ]

    sha256 = hashlib.sha256(
        data
    ).digest()

    print()
    print("==============================")
    print("ARCHIVO CARGADO")
    print("==============================")

    print(f"Archivo: {path}")
    print(f"Tamaño: {len(data)} bytes")
    print(f"Payload: {PAYLOAD_SIZE} bytes")
    print(f"Tramas DATA: {len(payloads)}")

    print(
        "SHA-256: "
        f"{sha256.hex()}"
    )

    return data, payloads, sha256


# ============================================================
# CONSTRUIR START PAYLOAD
# ============================================================

def build_start_payload(
    transfer_id,
    file_size,
    file_type
):

    baud_code = get_baud_code()

    hamming_mode = (
        0x01
        if HAMMING_ENABLED
        else 0x00
    )

    payload = (
        transfer_id.to_bytes(
            4,
            byteorder="big"
        )
        +
        file_size.to_bytes(
            4,
            byteorder="big"
        )
        +
        bytes([
            file_type,
            baud_code
        ])
        +
        PAYLOAD_SIZE.to_bytes(
            2,
            byteorder="big"
        )
        +
        bytes([
            WINDOW_SIZE,
            hamming_mode
        ])
    )

    return payload


# ============================================================
# ENVIAR START
# ============================================================

def send_start(
    ser,
    transfer_id,
    file_size,
    file_type
):

    payload = build_start_payload(
        transfer_id,
        file_size,
        file_type
    )

    frame = build_frame(
        control=TYPE_START,
        sequence=SEQ_CONTROL,
        ack=ACK_NONE,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print(
        f"TX START "
        f"id=0x{transfer_id:08X}"
    )


# ============================================================
# ESTABLECER SESION
# ============================================================

def establish_session(
    ser,
    receiver,
    transfer_id,
    file_size,
    file_type
):

    print()
    print("==============================")
    print("ESTABLECIENDO SESION")
    print("==============================")

    for attempt in range(
        MAX_RETRIES + 1
    ):

        send_start(
            ser,
            transfer_id,
            file_size,
            file_type
        )

        start_time = time.monotonic()

        while (
            time.monotonic() - start_time
            < TIMEOUT
        ):

            byte = ser.read(1)

            if not byte:
                continue

            frame = receiver.feed(byte)

            if frame is None:
                continue

            if (
                frame["control"]
                != TYPE_START_ACK
            ):
                continue

            payload = frame["payload"]

            if len(payload) != 5:
                continue

            received_id = int.from_bytes(
                payload[0:4],
                byteorder="big"
            )

            status = payload[4]

            if received_id != transfer_id:

                print(
                    "START_ACK ignorado: "
                    "ID incorrecto"
                )

                continue

            if status != STATUS_OK:

                print(
                    f"START rechazado. "
                    f"Status={status}"
                )

                return False

            print("RX START_ACK")

            print()
            print("==============================")
            print("SESION ESTABLECIDA")
            print("==============================")

            return True

        if attempt < MAX_RETRIES:

            print(
                f"TIMEOUT esperando "
                f"START_ACK "
                f"({attempt + 1}/"
                f"{MAX_RETRIES})"
            )

    return False


# ============================================================
# ENVIAR DATA
# ============================================================

def send_data(
    ser,
    payloads,
    index
):

    sequence = (
        index
        % SEQUENCE_SPACE
    )

    payload = payloads[index]

    frame = build_frame(
        control=TYPE_DATA,
        sequence=sequence,
        ack=ACK_NONE,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print(
        f"TX DATA "
        f"seq={sequence} "
        f"index={index} "
        f"bytes={len(payload)}"
    )


# ============================================================
# ENVIAR FIN
# ============================================================

def send_fin(
    ser,
    transfer_id,
    sha256
):

    payload = (
        transfer_id.to_bytes(
            4,
            byteorder="big"
        )
        +
        sha256
    )

    frame = build_frame(
        control=TYPE_FIN,
        sequence=SEQ_CONTROL,
        ack=ACK_NONE,
        payload=payload
    )

    ser.write(frame)
    ser.flush()

    print("TX FIN")


# ============================================================
# FINALIZAR SESION
# ============================================================

def finish_session(
    ser,
    receiver,
    transfer_id,
    sha256
):

    print()
    print("==============================")
    print("FINALIZANDO SESION")
    print("==============================")

    for attempt in range(
        MAX_RETRIES + 1
    ):

        send_fin(
            ser,
            transfer_id,
            sha256
        )

        start_time = time.monotonic()

        while (
            time.monotonic() - start_time
            < TIMEOUT
        ):

            byte = ser.read(1)

            if not byte:
                continue

            frame = receiver.feed(byte)

            if frame is None:
                continue

            if (
                frame["control"]
                != TYPE_FIN_ACK
            ):
                continue

            payload = frame["payload"]

            if len(payload) != 5:
                continue

            received_id = int.from_bytes(
                payload[0:4],
                byteorder="big"
            )

            status = payload[4]

            if received_id != transfer_id:
                continue

            print(
                f"RX FIN_ACK "
                f"status={status}"
            )

            if status == STATUS_OK:

                print()
                print("==============================")
                print("TRANSFERENCIA VERIFICADA")
                print("==============================")

                return True

            print()
            print("==============================")
            print("TRANSFERENCIA INVALIDA")
            print("==============================")

            return False

        if attempt < MAX_RETRIES:

            print(
                f"TIMEOUT esperando "
                f"FIN_ACK "
                f"({attempt + 1}/"
                f"{MAX_RETRIES})"
            )

    return False


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    try:

        file_type = get_file_type(
            FILE_PATH
        )

        (
            file_data,
            payloads,
            file_sha256
        ) = load_file(
            FILE_PATH
        )

    except (
        OSError,
        ValueError
    ) as error:

        print(error)

        return

    # ID aleatorio de 32 bits
    transfer_id = (
        secrets.randbits(32)
    )

    print(
        f"Transfer ID: "
        f"0x{transfer_id:08X}"
    )

    try:

        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=SERIAL_TIMEOUT
        )

    except serial.SerialException as error:

        print(error)

        return

    time.sleep(2)

    ser.reset_input_buffer()

    receiver = FrameReceiver()

    try:

        # =====================================================
        # START
        # =====================================================

        if not establish_session(
            ser,
            receiver,
            transfer_id,
            len(file_data),
            file_type
        ):

            print(
                "No fue posible "
                "establecer la sesion."
            )

            return

        # =====================================================
        # GO-BACK-N
        # =====================================================

        base = 0
        next_seq = 0

        timer_start = None

        retry_count = 0

        total_frames = len(
            payloads
        )

        transfer_aborted = False

        print()
        print("==============================")
        print("INICIANDO GO-BACK-N")
        print("==============================")

        while base < total_frames:

            # ---------------------------------------------
            # LLENAR VENTANA
            # ---------------------------------------------

            while (
                next_seq < total_frames
                and
                next_seq
                < base + WINDOW_SIZE
            ):

                send_data(
                    ser,
                    payloads,
                    next_seq
                )

                if base == next_seq:

                    timer_start = (
                        time.monotonic()
                    )

                next_seq += 1

            # ---------------------------------------------
            # RECIBIR ACK
            # ---------------------------------------------

            byte = ser.read(1)

            if byte:

                frame = receiver.feed(
                    byte
                )

                if frame is not None:

                    if (
                        frame["control"]
                        == TYPE_ACK
                        and
                        frame["sequence"]
                        == SEQ_CONTROL
                    ):

                        # Debe venir el transfer ID
                        if (
                            frame["payload"]
                            != transfer_id.to_bytes(
                                4,
                                "big"
                            )
                        ):

                            print(
                                "ACK ignorado: "
                                "Transfer ID incorrecto"
                            )

                            continue

                        ack = frame["ack"]

                        print(
                            f"RX ACK {ack}"
                        )

                        outstanding = (
                            next_seq - base
                        )

                        distance = (
                            ack
                            -
                            (
                                base
                                % SEQUENCE_SPACE
                            )
                        ) % SEQUENCE_SPACE

                        if (
                            distance
                            < outstanding
                        ):

                            new_base = (
                                base
                                + distance
                                + 1
                            )

                            print(
                                f"Ventana: "
                                f"{base} -> "
                                f"{new_base}"
                            )

                            base = new_base

                            retry_count = 0

                            if (
                                base
                                == next_seq
                            ):

                                timer_start = None

                            else:

                                timer_start = (
                                    time.monotonic()
                                )

            # ---------------------------------------------
            # TIMEOUT
            # ---------------------------------------------

            if (
                timer_start
                is not None
                and
                time.monotonic()
                - timer_start
                >= TIMEOUT
            ):

                retry_count += 1

                print(
                    f"TIMEOUT "
                    f"index={base}"
                )

                print(
                    f"Reintento "
                    f"{retry_count}/"
                    f"{MAX_RETRIES}"
                )

                if (
                    retry_count
                    > MAX_RETRIES
                ):

                    print(
                        "TRANSFERENCIA "
                        "ABORTADA"
                    )

                    transfer_aborted = True

                    break

                print(
                    f"GBN retransmitiendo "
                    f"{base}..."
                    f"{next_seq - 1}"
                )

                for index in range(
                    base,
                    next_seq
                ):

                    send_data(
                        ser,
                        payloads,
                        index
                    )

                timer_start = (
                    time.monotonic()
                )

        # =====================================================
        # FIN
        # =====================================================

        if not transfer_aborted:

            print()
            print("==============================")
            print("DATA COMPLETA")
            print("==============================")

            result = finish_session(
                ser,
                receiver,
                transfer_id,
                file_sha256
            )

            if not result:

                print(
                    "La verificacion final "
                    "fallo."
                )

    except KeyboardInterrupt:

        print(
            "\nTransferencia detenida."
        )

    finally:

        ser.close()


if __name__ == "__main__":
    main()