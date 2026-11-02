import argparse
import hashlib
import queue
import secrets
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import serial

if __package__:
    from . import protocol
else:
    import protocol

build_frame = protocol.build_frame
parse_frame = protocol.parse_frame
FRAME_FLAG = protocol.FRAME_FLAG
TYPE_DATA = protocol.TYPE_DATA
TYPE_ACK = protocol.TYPE_ACK
TYPE_START = protocol.TYPE_START
TYPE_FIN = protocol.TYPE_FIN
TYPE_ABORT = protocol.TYPE_ABORT
TYPE_START_ACK = protocol.TYPE_START_ACK
TYPE_FIN_ACK = protocol.TYPE_FIN_ACK
TYPE_HAMMING_STATS = protocol.TYPE_HAMMING_STATS
ACK_NONE = protocol.ACK_NONE
SEQ_CONTROL = protocol.SEQ_CONTROL


# ============================================================
# CONFIGURACION GENERAL
# ============================================================

SERIAL_TIMEOUT = 0.05
USB_BAUD_RATE = 9600
USB_CHUNK_SIZE = 16
USB_LOCAL_DATA = 0x31
USB_LOCAL_ACK = 0x32
USB_LOCAL_CONFIG = 0x33
USB_LOCAL_CONFIG_ACK = 0x34
USB_LOCAL_FLAG = 0x7E
USB_LOCAL_ESCAPE = 0x7D
USB_LOCAL_XOR = 0x20

SEQUENCE_SPACE = 16

MAX_RETRIES = 5
TIMEOUT = 2.0

DEFAULT_BAUD_RATE = 9600
DEFAULT_WINDOW_SIZE = 4
DEFAULT_PAYLOAD_SIZE = 500

DEFAULT_HAMMING_ENABLED = False

OUTPUT_DIRECTORY = "."


# ============================================================
# TIPOS DE ARCHIVO
# ============================================================

FILE_TYPE_TXT = 0x01
FILE_TYPE_PDF = 0x02
FILE_TYPE_PNG = 0x03


# ============================================================
# CODIGOS DE VELOCIDAD
# ============================================================

BAUD_CODE_9600 = 0x01
BAUD_CODE_19200 = 0x02


# ============================================================
# STATUS
# ============================================================

STATUS_OK = 0x00

STATUS_INVALID_PARAMETERS = 0x01
STATUS_SIZE_ERROR = 0x02
STATUS_HASH_ERROR = 0x03
STATUS_STORAGE_ERROR = 0x04
STATUS_BUSY = 0x05


# ============================================================
# CAUSAS ABORT
# ============================================================

ABORT_START_TIMEOUT = 0x01
ABORT_DATA_RETRIES = 0x02
ABORT_FIN_TIMEOUT = 0x03
ABORT_USER_CANCEL = 0x04
ABORT_REMOTE_ERROR = 0x05


# ============================================================
# RECEPTOR DE BYTES / FRAMING
# ============================================================

class FrameReceiver:

    def __init__(self, log=print):

        self.log = log
        self.buffer = bytearray()
        self.receiving = False

    def feed(self, byte):

        value = byte[0]

        # ----------------------------------------------------
        # BUSCAR DELIMITADOR INICIAL
        # ----------------------------------------------------

        if not self.receiving:

            if value == FRAME_FLAG:

                self.buffer.clear()
                self.buffer.append(value)

                self.receiving = True

            return None

        # ----------------------------------------------------
        # RECIBIENDO TRAMA
        # ----------------------------------------------------

        self.buffer.append(value)

        # Delimitador final
        if value == FRAME_FLAG:

            try:

                frame = parse_frame(
                    bytes(self.buffer)
                )

            except ValueError as error:

                self.log(
                    f"\n[RX] Trama invalida: {error}"
                )

                frame = None

            self.buffer.clear()
            self.receiving = False

            return frame

        return None


class UsbLocalReceiver:
    """Decode the small local USB transport used between PC and Arduino."""
    def __init__(self):
        self.buffer = bytearray()
        self.receiving = False
        self.escaped = False

    def feed(self, value):
        if value == USB_LOCAL_FLAG:
            if not self.receiving:
                self.receiving = True
                self.buffer.clear()
                self.escaped = False
                return None
            packet = bytes(self.buffer)
            self.buffer.clear()
            self.receiving = True
            self.escaped = False
            if len(packet) < 4 or packet[2] > USB_CHUNK_SIZE or len(packet) != 4 + packet[2]:
                return None
            checksum = 0
            for byte in packet[:-1]:
                checksum ^= byte
            if checksum != packet[-1]:
                return None
            return packet[0], packet[1], packet[3:-1]
        if not self.receiving:
            return None
        if self.escaped:
            value ^= USB_LOCAL_XOR
            self.escaped = False
        elif value == USB_LOCAL_ESCAPE:
            self.escaped = True
            return None
        self.buffer.append(value)
        if len(self.buffer) > USB_CHUNK_SIZE + 4:
            self.buffer.clear()
            self.receiving = False
        return None


def build_usb_local_packet(kind, sequence, payload=b""):
    body = bytearray((kind, sequence, len(payload)))
    body.extend(payload)
    checksum = 0
    for byte in body:
        checksum ^= byte
    body.append(checksum)
    escaped = bytearray()
    for byte in body:
        if byte in (USB_LOCAL_FLAG, USB_LOCAL_ESCAPE):
            escaped.extend((USB_LOCAL_ESCAPE, byte ^ USB_LOCAL_XOR))
        else:
            escaped.append(byte)
    return bytes((USB_LOCAL_FLAG,)) + bytes(escaped) + bytes((USB_LOCAL_FLAG,))


# ============================================================
# ENDPOINT FULL DUPLEX
# ============================================================

class Endpoint:

    def __init__(
        self,
        port,
        baud_rate,
        window_size,
        payload_size,
        hamming_enabled,
        on_event=None,
        output_directory=OUTPUT_DIRECTORY,
        timeout=TIMEOUT
    ):

        self.on_event = on_event
        self.output_directory = Path(output_directory)
        self.timeout = timeout
        self.port = port

        self.baud_rate = baud_rate
        self.window_size = window_size
        self.payload_size = payload_size

        self.hamming_enabled = (
            hamming_enabled
        )

        # ----------------------------------------------------
        # SERIAL
        # ----------------------------------------------------

        self.ser = None

        # Protege las escrituras seriales.
        #
        # ACK y DATA pueden ser generados desde hilos
        # diferentes, pero no deben entremezclar sus bytes.
        self.serial_write_lock = (
            threading.Lock()
        )
        self.local_ack_condition = threading.Condition()
        self.local_ack_sequence = None
        self.local_tx_sequence = 0

        # El hilo que lee el USB nunca debe ejecutar handlers que puedan
        # volver a escribir al mismo puerto. De lo contrario, un ACK de
        # enlace puede bloquear esperando el ACK local que solo ese mismo
        # hilo podría leer. Las tramas completas pasan a esta cola y se
        # despachan desde un hilo independiente.
        self.frame_queue = queue.Queue()
        self.dispatch_thread = None

        # ----------------------------------------------------
        # CONTROL DE EJECUCION
        # ----------------------------------------------------

        self.running = (
            threading.Event()
        )

        self.running.set()

        # ----------------------------------------------------
        # THREAD RX
        # ----------------------------------------------------

        self.rx_thread = None

        # ----------------------------------------------------
        # THREAD TX
        # ----------------------------------------------------

        self.tx_thread = None

        self.tx_busy_lock = (
            threading.Lock()
        )

        # ----------------------------------------------------
        # COLAS DE RESPUESTAS PARA TX
        # ----------------------------------------------------

        self.start_ack_queue = (
            queue.Queue()
        )

        self.ack_queue = (
            queue.Queue()
        )

        self.fin_ack_queue = (
            queue.Queue()
        )

        self.abort_queue = (
            queue.Queue()
        )

        # ====================================================
        # ESTADO TX
        # ====================================================

        self.tx_transfer_id = None

        self.tx_cancel_requested = (
            threading.Event()
        )

        # ====================================================
        # ESTADO RX
        # ====================================================

        self.rx_session_active = False

        self.rx_transfer_id = None

        self.rx_expected_sequence = 0

        self.rx_expected_file_size = None

        self.rx_file_type = None

        self.rx_received_data = (
            bytearray()
        )

        # Resultado de la transferencia terminada más
        # recientemente. Permite responder FIN repetidos.

        self.last_finished_id = None
        self.last_finish_status = None


    # ========================================================
    # CONEXION SERIAL
    # ========================================================

    def emit(self, kind, **data):
        if self.on_event is not None:
            self.on_event(kind, **data)

    def log(self, *args):
        if self.on_event is None:
            print(*args)
        else:
            self.emit("log", text=" ".join(str(arg) for arg in args))

    def trace_frame(self, direction, frame, raw):
        names = {
            TYPE_START: "START", TYPE_START_ACK: "START_ACK",
            TYPE_DATA: "DATA", TYPE_ACK: "ACK", TYPE_FIN: "FIN",
            TYPE_FIN_ACK: "FIN_ACK", TYPE_ABORT: "ABORT",
            TYPE_HAMMING_STATS: "HAMMING_STATS",
        }
        self.emit("frame", direction=direction, name=names.get(frame["control"], "?"),
                  sequence=frame["sequence"], ack=frame["ack"],
                  size=len(frame["payload"]), raw=raw.hex(" "))

    def open(self):

        self.ser = serial.Serial(
            self.port,
            USB_BAUD_RATE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=2
        )

        time.sleep(2)

        self.ser.reset_input_buffer()

        self.log()
        self.log("==============================")
        self.log("ENDPOINT INICIADO")
        self.log("==============================")

        self.log(
            f"Puerto:  {self.port}"
        )

        self.log(
            f"USB:     {USB_BAUD_RATE} bps"
        )

        self.log(
            f"Enlace:  {self.baud_rate} bps"
        )

        self.log(
            f"Ventana: {self.window_size}"
        )

        self.log(
            f"Payload: {self.payload_size}"
        )

        self.log(
            f"Hamming: "
            f"{self.hamming_enabled}"
        )

        # Iniciar recepción permanente

        self.rx_thread = threading.Thread(
            target=self._rx_loop,
            daemon=True
        )

        self.rx_thread.start()

        # Configurar la capa física del Arduino antes de intercambiar
        # cualquier trama del protocolo. Esto sincroniza baud y Hamming.
        self._configure_arduino()

        self.dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            daemon=True
        )
        self.dispatch_thread.start()


    # ========================================================
    # CERRAR
    # ========================================================

    def close(self):

        self.running.clear()
        with self.local_ack_condition:
            self.local_ack_condition.notify_all()

        self.tx_cancel_requested.set()

        if (
            self.tx_thread is not None
            and self.tx_thread.is_alive()
        ):

            self.tx_thread.join(
                timeout=2
            )

        if (
            self.dispatch_thread is not None
            and self.dispatch_thread.is_alive()
        ):
            self.frame_queue.put(None)
            self.dispatch_thread.join(timeout=1)

        if (
            self.rx_thread is not None
            and self.rx_thread.is_alive()
        ):

            self.rx_thread.join(
                timeout=1
            )

        if (
            self.ser is not None
            and self.ser.is_open
        ):

            self.ser.close()

        self.log()
        self.log("Endpoint cerrado.")


    # ========================================================
    # ESCRITURA SERIAL SEGURA
    # ========================================================

    def _send_local_packet_wait_ack(self, kind, payload=b"", timeout=3.0):
        """Envía un paquete PC->Arduino y espera su confirmación local."""
        sequence = self.local_tx_sequence
        self.local_tx_sequence = (sequence + 1) & 0xFF
        packet = build_usb_local_packet(kind, sequence, payload)
        with self.local_ack_condition:
            # Evita aceptar por accidente una confirmación vieja con el
            # mismo número después del wrap de 8 bits.
            self.local_ack_sequence = None
        self.ser.write(packet)
        self.ser.flush()
        deadline = time.monotonic() + timeout
        with self.local_ack_condition:
            while self.local_ack_sequence != sequence and self.running.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise serial.SerialTimeoutException(
                        f"Arduino no confirmó el paquete USB {sequence} (tipo 0x{kind:02X})"
                    )
                self.local_ack_condition.wait(remaining)
            self.local_ack_sequence = None

    def _configure_arduino(self):
        payload = bytes((self._baud_code(), 0x01 if self.hamming_enabled else 0x00))
        with self.serial_write_lock:
            self._send_local_packet_wait_ack(USB_LOCAL_CONFIG, payload, timeout=3.0)
        self.log(f"Arduino configurado: baud={self.baud_rate}, Hamming={self.hamming_enabled}")

    def _send_frame(self, frame):
        with self.serial_write_lock:
            offset = 0
            while offset < len(frame) and self.running.is_set():
                chunk = frame[offset:offset + USB_CHUNK_SIZE]
                self._send_local_packet_wait_ack(USB_LOCAL_DATA, chunk, timeout=3.0)
                offset += len(chunk)
        self.trace_frame("TX", parse_frame(frame), frame)


    # ========================================================
    # LOOP RX PERMANENTE
    # ========================================================

    def _rx_loop(self):

        parser = FrameReceiver(self.log)
        local_parser = UsbLocalReceiver()

        while self.running.is_set():

            try:

                byte = self.ser.read(1)

            except serial.SerialException as error:

                self.log(
                    f"\nError serial RX: {error}"
                )

                self.running.clear()

                break

            if not byte:
                continue

            packet = local_parser.feed(byte[0])
            if packet is None:
                continue
            kind, sequence, payload = packet
            if kind in (USB_LOCAL_ACK, USB_LOCAL_CONFIG_ACK) and not payload:
                with self.local_ack_condition:
                    self.local_ack_sequence = sequence
                    self.local_ack_condition.notify_all()
            elif kind == USB_LOCAL_DATA:
                for raw_byte in payload:
                    frame = parser.feed(bytes((raw_byte,)))
                    if frame is not None:
                        self.frame_queue.put(frame)

    def _dispatch_loop(self):
        while self.running.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if frame is None:
                break
            try:
                self._dispatch_frame(frame)
            except Exception as error:
                self.log(f"Error procesando trama recibida: {error}")


    # ========================================================
    # DISPATCH
    # ========================================================

    def _dispatch_frame(self, frame):

        self.trace_frame("RX", frame, build_frame(
            frame["control"], frame["sequence"], frame["ack"], frame["payload"]))
        control = frame["control"]

        # ----------------------------------------------------
        # RESPUESTAS ASOCIADAS A NUESTRA TRANSMISION
        # ----------------------------------------------------

        if control == TYPE_START_ACK:

            self._handle_start_ack(
                frame
            )

            return

        if control == TYPE_ACK:

            self._handle_ack(
                frame
            )

            return

        if control == TYPE_FIN_ACK:

            self._handle_fin_ack(
                frame
            )

            return

        if control == TYPE_HAMMING_STATS:
            payload = frame["payload"]
            if len(payload) != 30:
                self.log(f"[RX] HAMMING_STATS descartada: longitud {len(payload)}")
                return
            read_u32 = lambda offset: int.from_bytes(payload[offset:offset + 4], "big")
            read_u16 = lambda offset: int.from_bytes(payload[offset:offset + 2], "big")
            self.emit(
                "hamming_stats", frame_id=read_u32(0),
                total_corrected=read_u32(4), total_global=read_u32(8),
                total_double=read_u32(12), blocks=read_u16(16),
                corrected=read_u16(18), global_parity=read_u16(20),
                double=read_u16(22), last_block=read_u16(24),
                status=payload[26], position=payload[27],
                word=int.from_bytes(payload[28:30], "big"))
            return

        # ----------------------------------------------------
        # TRAMAS DE LA TRANSMISION DEL REMOTO HACIA NOSOTROS
        # ----------------------------------------------------

        if control == TYPE_START:

            self._handle_rx_start(
                frame
            )

            return

        if control == TYPE_DATA:

            self._handle_rx_data(
                frame
            )

            return

        if control == TYPE_FIN:

            self._handle_rx_fin(
                frame
            )

            return

        if control == TYPE_ABORT:

            self._handle_abort(
                frame
            )

            return

        self.log(
            f"\n[RX] Tipo de trama "
            f"desconocido: {control}"
        )


    # ========================================================
    # START_ACK PARA TX
    # ========================================================

    def _handle_start_ack(
        self,
        frame
    ):

        payload = frame["payload"]

        if len(payload) != 5:
            return

        transfer_id = int.from_bytes(
            payload[0:4],
            byteorder="big"
        )

        status = payload[4]

        if (
            self.tx_transfer_id
            is None
        ):

            return

        if (
            transfer_id
            != self.tx_transfer_id
        ):

            return

        self.start_ack_queue.put(
            status
        )


    # ========================================================
    # ACK PARA TX
    # ========================================================

    def _handle_ack(
        self,
        frame
    ):

        payload = frame["payload"]

        # ACK contiene Transfer ID
        if len(payload) != 4:
            return

        transfer_id = int.from_bytes(
            payload,
            byteorder="big"
        )

        if (
            self.tx_transfer_id
            is None
        ):

            return

        if (
            transfer_id
            != self.tx_transfer_id
        ):

            return

        self.ack_queue.put(
            frame["ack"]
        )


    # ========================================================
    # FIN_ACK PARA TX
    # ========================================================

    def _handle_fin_ack(
        self,
        frame
    ):

        payload = frame["payload"]

        if len(payload) != 5:
            return

        transfer_id = int.from_bytes(
            payload[0:4],
            byteorder="big"
        )

        status = payload[4]

        if (
            self.tx_transfer_id
            is None
        ):

            return

        if (
            transfer_id
            != self.tx_transfer_id
        ):

            return

        self.fin_ack_queue.put(
            status
        )


    # ========================================================
    # START REMOTO
    # ========================================================

    def _handle_rx_start(
        self,
        frame
    ):

        try:

            info = (
                self._parse_start_payload(
                    frame["payload"]
                )
            )

        except ValueError as error:

            self.log(
                f"\n[RX] START invalido: "
                f"{error}"
            )

            return

        transfer_id = (
            info["transfer_id"]
        )

        self.log()
        self.log("==============================")
        self.log("RX START")
        self.log("==============================")

        self.log(
            f"Transfer ID: "
            f"0x{transfer_id:08X}"
        )

        self.log(
            f"Tamaño: "
            f"{info['file_size']} bytes"
        )

        self.log(
            f"Payload: "
            f"{info['payload_size']}"
        )

        self.log(
            f"Ventana: "
            f"{info['window_size']}"
        )

        # ----------------------------------------------------
        # START REPETIDO
        # ----------------------------------------------------

        if (
            self.rx_session_active
            and
            transfer_id
            == self.rx_transfer_id
        ):

            self.log(
                "[RX] START repetido"
            )

            self._send_start_ack(
                transfer_id,
                STATUS_OK
            )

            return

        # ----------------------------------------------------
        # YA EXISTE OTRA RECEPCION ACTIVA
        # ----------------------------------------------------

        if self.rx_session_active:

            self.log(
                "[RX] START rechazado: "
                "receptor ocupado"
            )

            self._send_start_ack(
                transfer_id,
                STATUS_BUSY
            )

            return

        # ----------------------------------------------------
        # VALIDAR CONFIGURACION
        # ----------------------------------------------------

        if not self._validate_start(
            info
        ):

            self.log(
                "[RX] Parametros incompatibles"
            )

            self._send_start_ack(
                transfer_id,
                STATUS_INVALID_PARAMETERS
            )

            return

        # ----------------------------------------------------
        # INICIAR RECEPCION
        # ----------------------------------------------------

        self.rx_transfer_id = (
            transfer_id
        )

        self.rx_expected_file_size = (
            info["file_size"]
        )

        self.rx_file_type = (
            info["file_type"]
        )

        self.rx_expected_sequence = 0

        self.rx_received_data.clear()

        self.rx_session_active = True
        self.emit("receiving", role="receive", transfer_id=transfer_id,
                  total=self.rx_expected_file_size)

        self._send_start_ack(
            transfer_id,
            STATUS_OK
        )

        self.log(
            "[RX] Sesion establecida. "
            "Esperando seq=0"
        )


    # ========================================================
    # DATA REMOTO
    # ========================================================

    def _handle_rx_data(
        self,
        frame
    ):

        if not self.rx_session_active:

            self.log(
                "\n[RX] DATA ignorada: "
                "no existe sesion activa"
            )

            return

        sequence = frame["sequence"]

        # ----------------------------------------------------
        # DATA ESPERADA
        # ----------------------------------------------------

        if (
            sequence
            == self.rx_expected_sequence
        ):

            payload = frame["payload"]

            self.rx_received_data.extend(
                payload
            )
            self.emit("progress", role="receive", current=len(self.rx_received_data),
                      total=self.rx_expected_file_size)

            self.log(
                f"\n[RX] DATA "
                f"seq={sequence} "
                f"bytes={len(payload)} "
                f"total="
                f"{len(self.rx_received_data)}"
            )

            self._send_ack(
                sequence,
                self.rx_transfer_id
            )

            self.rx_expected_sequence = (
                self.rx_expected_sequence + 1
            ) % SEQUENCE_SPACE

            return

        # ----------------------------------------------------
        # FUERA DE ORDEN
        # ----------------------------------------------------

        self.log(
            f"\n[RX] DATA fuera de orden "
            f"seq={sequence}, "
            f"esperado="
            f"{self.rx_expected_sequence}"
        )

        last_valid = (
            self.rx_expected_sequence - 1
        ) % SEQUENCE_SPACE

        self._send_ack(
            last_valid,
            self.rx_transfer_id
        )


    # ========================================================
    # FIN REMOTO
    # ========================================================

    def _handle_rx_fin(
        self,
        frame
    ):

        payload = frame["payload"]

        if len(payload) != 36:

            self.log(
                "\n[RX] FIN invalido"
            )

            return

        transfer_id = int.from_bytes(
            payload[0:4],
            byteorder="big"
        )

        expected_sha256 = (
            payload[4:36]
        )

        self.log()
        self.log("==============================")
        self.log("RX FIN")
        self.log("==============================")

        self.log(
            f"Transfer ID: "
            f"0x{transfer_id:08X}"
        )

        # ----------------------------------------------------
        # FIN REPETIDO
        # ----------------------------------------------------

        if (
            not self.rx_session_active
            and
            transfer_id
            == self.last_finished_id
        ):

            self.log(
                "[RX] FIN repetido"
            )

            self._send_fin_ack(
                transfer_id,
                self.last_finish_status
            )

            return

        # ----------------------------------------------------
        # VALIDAR SESION
        # ----------------------------------------------------

        if (
            not self.rx_session_active
            or
            transfer_id
            != self.rx_transfer_id
        ):

            self.log(
                "[RX] FIN no corresponde "
                "a la sesion actual"
            )

            return

        # ----------------------------------------------------
        # VALIDAR TAMAÑO
        # ----------------------------------------------------

        if (
            len(self.rx_received_data)
            != self.rx_expected_file_size
        ):

            status = (
                STATUS_SIZE_ERROR
            )

            self.log(
                "[RX] ERROR DE TAMAÑO"
            )

            self.log(
                f"Esperado: "
                f"{self.rx_expected_file_size}"
            )

            self.log(
                f"Recibido: "
                f"{len(self.rx_received_data)}"
            )

        else:

            calculated_sha256 = (
                hashlib.sha256(
                    self.rx_received_data
                ).digest()
            )

            self.log(
                f"SHA esperado:  "
                f"{expected_sha256.hex()}"
            )

            self.log(
                f"SHA calculado: "
                f"{calculated_sha256.hex()}"
            )

            if (
                calculated_sha256
                != expected_sha256
            ):

                status = (
                    STATUS_HASH_ERROR
                )

                self.log(
                    "[RX] SHA-256 INCORRECTO"
                )

            else:

                status = STATUS_OK

        # ----------------------------------------------------
        # GUARDAR
        # ----------------------------------------------------

        if status == STATUS_OK:

            extension = (
                self._get_extension(
                    self.rx_file_type
                )
            )

            output_file = (
                self.output_directory
                /
                (
                    "archivo_recibido_"
                    f"{transfer_id:08X}"
                    f"{extension}"
                )
            )

            try:

                self.output_directory.mkdir(parents=True, exist_ok=True)
                with open(
                    output_file,
                    "wb"
                ) as file:

                    file.write(
                        self.rx_received_data
                    )

                self.log()
                self.log(
                    "[RX] ARCHIVO VERIFICADO"
                )

                self.log(
                    f"[RX] Guardado: "
                    f"{output_file}"
                )

                self.log(
                    "[RX] SHA-256 CORRECTO"
                )

            except OSError as error:

                self.log(
                    f"[RX] Error guardando: "
                    f"{error}"
                )

                status = (
                    STATUS_STORAGE_ERROR
                )

        # ----------------------------------------------------
        # RECORDAR RESULTADO
        # ----------------------------------------------------

        if status == STATUS_OK:
            self.emit("received", role="receive", path=str(output_file.resolve()),
                      total=len(self.rx_received_data))
        else:
            self.emit("rejected", message=f"Error al recibir el archivo: estado {status}")

        self.last_finished_id = (
            transfer_id
        )

        self.last_finish_status = (
            status
        )

        # ----------------------------------------------------
        # FIN_ACK
        # ----------------------------------------------------

        self._send_fin_ack(
            transfer_id,
            status
        )

        # ----------------------------------------------------
        # LIMPIAR RX
        # ----------------------------------------------------

        self._reset_rx_session()

        self.log(
            "[RX] Esperando nuevo START..."
        )


    # ========================================================
    # ABORT
    # ========================================================

    def _handle_abort(
        self,
        frame
    ):

        payload = frame["payload"]

        if len(payload) != 5:

            self.log(
                "\n[RX] ABORT invalido"
            )

            return

        transfer_id = int.from_bytes(
            payload[0:4],
            byteorder="big"
        )

        cause = payload[4]

        self.log()
        self.log("==============================")
        self.log("RX ABORT")
        self.log("==============================")

        self.log(
            f"Transfer ID: "
            f"0x{transfer_id:08X}"
        )

        self.log(
            f"Causa: "
            f"{self._abort_description(cause)}"
        )

        # ----------------------------------------------------
        # Puede referirse a la transferencia que estamos
        # recibiendo del remoto.
        # ----------------------------------------------------

        if (
            self.rx_session_active
            and
            transfer_id
            == self.rx_transfer_id
        ):

            self.log(
                "[RX] Cancelando "
                "recepcion activa"
            )

            self._reset_rx_session()

        # ----------------------------------------------------
        # También puede cancelar nuestra TX si en el futuro
        # el receptor remoto decide abortarla.
        # ----------------------------------------------------

        if (
            self.tx_transfer_id
            is not None
            and
            transfer_id
            == self.tx_transfer_id
        ):

            self.abort_queue.put(
                (
                    transfer_id,
                    cause
                )
            )


    # ========================================================
    # ENVIAR ARCHIVO
    # ========================================================

    def send_file(self, path):

        # Solo una transmisión local a la vez.

        if not self.tx_busy_lock.acquire(
            blocking=False
        ):

            self.log(
                "Ya existe una transmision "
                "local activa."
            )

            return False

        completed = False
        try:

            completed = self._send_file_worker(path)
            return completed

        except Exception as error:
            self.log(f"Error de envío: {error}")
            return False

        finally:

            cancelled = self.tx_cancel_requested.is_set()
            self.tx_transfer_id = None

            self.tx_cancel_requested.clear()

            self._clear_tx_queues()

            self.tx_busy_lock.release()
            self.emit("send_done", completed=completed, cancelled=cancelled)


    # ========================================================
    # WORKER DE TRANSMISION
    # ========================================================

    def _send_file_worker(
        self,
        path
    ):

        try:

            file_type = (
                self._get_file_type(
                    path
                )
            )

            with open(
                path,
                "rb"
            ) as file:

                file_data = file.read()

        except (
            OSError,
            ValueError
        ) as error:

            self.log(
                f"Error: {error}"
            )

            return False

        self.emit("progress", role="send", current=0, total=len(file_data))

        payloads = [
            file_data[
                i:i + self.payload_size
            ]
            for i in range(
                0,
                len(file_data),
                self.payload_size
            )
        ]

        sha256 = hashlib.sha256(
            file_data
        ).digest()

        transfer_id = (
            secrets.randbits(32)
        )

        self.tx_transfer_id = (
            transfer_id
        )

        self._clear_tx_queues()

        self.log()
        self.log("==============================")
        self.log("NUEVA TRANSMISION")
        self.log("==============================")

        self.log(
            f"Archivo: {path}"
        )

        self.log(
            f"Transfer ID: "
            f"0x{transfer_id:08X}"
        )

        self.log(
            f"Tamaño: "
            f"{len(file_data)} bytes"
        )

        self.log(
            f"DATA: {len(payloads)} tramas"
        )

        self.log(
            f"SHA-256: {sha256.hex()}"
        )

        # ====================================================
        # START
        # ====================================================

        if not self._tx_start(
            transfer_id,
            len(file_data),
            file_type
        ):

            self.log(
                "[TX] No fue posible "
                "establecer la sesion."
            )

            self._send_abort(
                transfer_id,
                ABORT_START_TIMEOUT
            )

            return False

        # ====================================================
        # GBN
        # ====================================================

        if not self._tx_gbn(
            transfer_id,
            payloads
        ):

            return False

        # ====================================================
        # FIN
        # ====================================================

        if not self._tx_fin(
            transfer_id,
            sha256
        ):

            self._send_abort(
                transfer_id,
                ABORT_FIN_TIMEOUT
            )

            return False

        self.log()
        self.log("==============================")
        self.log("TRANSFERENCIA COMPLETADA")
        self.log("==============================")

        self.emit("sent", role="send", total=len(file_data))
        return True


    # ========================================================
    # TX START
    # ========================================================

    def _tx_start(
        self,
        transfer_id,
        file_size,
        file_type
    ):

        for attempt in range(
            MAX_RETRIES + 1
        ):

            if self._tx_cancelled():
                return False

            self._send_start(
                transfer_id,
                file_size,
                file_type
            )

            self.log(
                f"[TX] START "
                f"intento={attempt + 1}"
            )

            deadline = (
                time.monotonic()
                + self.timeout
            )

            while (
                time.monotonic()
                < deadline
            ):

                if self._tx_cancelled():
                    return False

                abort = (
                    self._get_remote_abort()
                )

                if abort is not None:

                    self.log(
                        "[TX] Transferencia "
                        "abortada por remoto"
                    )

                    return False

                try:

                    status = (
                        self.start_ack_queue.get(
                            timeout=0.05
                        )
                    )

                except queue.Empty:
                    continue

                if status == STATUS_OK:

                    self.log(
                        "[TX] RX START_ACK OK"
                    )

                    return True

                self.log(
                    f"[TX] START rechazado "
                    f"status={status}"
                )

                return False

            if attempt < MAX_RETRIES:

                self.log(
                    "[TX] TIMEOUT START, "
                    "retransmitiendo..."
                )

        return False


    # ========================================================
    # TX GO-BACK-N
    # ========================================================

    def _tx_gbn(
        self,
        transfer_id,
        payloads
    ):

        total_frames = len(
            payloads
        )
        total_bytes = sum(len(payload) for payload in payloads)

        # Archivo vacío: no hay DATA
        if total_frames == 0:

            self.log(
                "[TX] Archivo vacio: "
                "sin DATA"
            )

            return True

        base = 0
        next_index = 0

        timer_start = None

        retry_count = 0

        self.log()
        self.log(
            "[TX] Iniciando Go-Back-N"
        )

        while base < total_frames:

            if self._tx_cancelled():

                self._send_abort(
                    transfer_id,
                    ABORT_USER_CANCEL
                )

                return False

            abort = (
                self._get_remote_abort()
            )

            if abort is not None:

                self.log(
                    "[TX] ABORT recibido "
                    "desde remoto"
                )

                return False

            # ------------------------------------------------
            # LLENAR VENTANA
            # ------------------------------------------------

            while (
                next_index
                < total_frames
                and
                next_index
                < base + self.window_size
            ):

                self._send_data(
                    payloads,
                    next_index
                )

                if (
                    next_index
                    == base
                ):

                    timer_start = (
                        time.monotonic()
                    )

                next_index += 1

            # ------------------------------------------------
            # PROCESAR ACK
            # ------------------------------------------------

            try:

                ack = (
                    self.ack_queue.get(
                        timeout=0.02
                    )
                )

                outstanding = (
                    next_index - base
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

                    self.log(
                        f"[TX] ACK {ack}: "
                        f"base "
                        f"{base} -> "
                        f"{new_base}"
                    )

                    base = new_base
                    self.emit("progress", role="send",
                              current=min(base * self.payload_size, total_bytes),
                              total=total_bytes)

                    retry_count = 0

                    if (
                        base
                        == next_index
                    ):

                        timer_start = None

                    else:

                        timer_start = (
                            time.monotonic()
                        )

            except queue.Empty:
                pass

            # ------------------------------------------------
            # TIMEOUT
            # ------------------------------------------------

            if (
                timer_start
                is not None
                and
                (
                    time.monotonic()
                    - timer_start
                    >= self.timeout
                )
            ):

                retry_count += 1

                self.log()
                self.log(
                    f"[TX] TIMEOUT "
                    f"base={base}"
                )

                self.log(
                    f"[TX] Reintento "
                    f"{retry_count}/"
                    f"{MAX_RETRIES}"
                )

                if (
                    retry_count
                    > MAX_RETRIES
                ):

                    self.log(
                        "[TX] MAX_RETRIES "
                        "SUPERADO"
                    )

                    self._send_abort(
                        transfer_id,
                        ABORT_DATA_RETRIES
                    )

                    return False

                self.log(
                    f"[TX] GBN: "
                    f"retransmitiendo "
                    f"{base}..."
                    f"{next_index - 1}"
                )

                for index in range(
                    base,
                    next_index
                ):

                    self._send_data(
                        payloads,
                        index
                    )

                timer_start = (
                    time.monotonic()
                )

        self.log(
            "[TX] Todas las DATA "
            "confirmadas"
        )

        return True


    # ========================================================
    # TX FIN
    # ========================================================

    def _tx_fin(
        self,
        transfer_id,
        sha256
    ):

        for attempt in range(
            MAX_RETRIES + 1
        ):

            if self._tx_cancelled():
                return False

            self._send_fin(
                transfer_id,
                sha256
            )

            self.log(
                f"[TX] FIN "
                f"intento={attempt + 1}"
            )

            deadline = (
                time.monotonic()
                + self.timeout
            )

            while (
                time.monotonic()
                < deadline
            ):

                if self._tx_cancelled():
                    return False

                abort = (
                    self._get_remote_abort()
                )

                if abort is not None:

                    self.log(
                        "[TX] ABORT remoto "
                        "durante FIN"
                    )

                    return False

                try:

                    status = (
                        self.fin_ack_queue.get(
                            timeout=0.05
                        )
                    )

                except queue.Empty:
                    continue

                if status == STATUS_OK:

                    self.log(
                        "[TX] RX FIN_ACK OK"
                    )

                    return True

                self.log(
                    f"[TX] FIN_ACK "
                    f"status={status}"
                )

                return False

            if attempt < MAX_RETRIES:

                self.log(
                    "[TX] TIMEOUT FIN, "
                    "retransmitiendo..."
                )

        return False


    # ========================================================
    # SOLICITAR CANCELACION LOCAL
    # ========================================================

    def cancel_transmission(self):

        if self.tx_transfer_id is None:

            self.log(
                "No existe transmision "
                "local activa."
            )

            return

        self.tx_cancel_requested.set()

        self._send_abort(
            self.tx_transfer_id,
            ABORT_USER_CANCEL
        )

        self.log(
            "[TX] Cancelacion solicitada."
        )


    # ========================================================
    # SEND START
    # ========================================================

    def _send_start(
        self,
        transfer_id,
        file_size,
        file_type
    ):

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
                self._baud_code()
            ])
            +
            self.payload_size.to_bytes(
                2,
                byteorder="big"
            )
            +
            bytes([
                self.window_size,
                (
                    0x01
                    if self.hamming_enabled
                    else 0x00
                )
            ])
        )

        frame = build_frame(
            control=TYPE_START,
            sequence=SEQ_CONTROL,
            ack=ACK_NONE,
            payload=payload
        )

        self._send_frame(frame)


    # ========================================================
    # SEND START_ACK
    # ========================================================

    def _send_start_ack(
        self,
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

        self._send_frame(frame)

        self.log(
            f"[RX] TX START_ACK "
            f"status={status}"
        )


    # ========================================================
    # SEND DATA
    # ========================================================

    def _send_data(
        self,
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

        self._send_frame(frame)

        self.log(
            f"[TX] DATA "
            f"index={index} "
            f"seq={sequence} "
            f"bytes={len(payload)}"
        )


    # ========================================================
    # SEND ACK
    # ========================================================

    def _send_ack(
        self,
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

        self._send_frame(frame)

        self.log(
            f"[RX] TX ACK {sequence}"
        )


    # ========================================================
    # SEND FIN
    # ========================================================

    def _send_fin(
        self,
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

        self._send_frame(frame)


    # ========================================================
    # SEND FIN_ACK
    # ========================================================

    def _send_fin_ack(
        self,
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

        self._send_frame(frame)

        self.log(
            f"[RX] TX FIN_ACK "
            f"status={status}"
        )


    # ========================================================
    # SEND ABORT
    # ========================================================

    def _send_abort(
        self,
        transfer_id,
        cause
    ):

        payload = (
            transfer_id.to_bytes(
                4,
                byteorder="big"
            )
            +
            bytes([cause])
        )

        frame = build_frame(
            control=TYPE_ABORT,
            sequence=SEQ_CONTROL,
            ack=ACK_NONE,
            payload=payload
        )

        try:

            self._send_frame(frame)

            self.log(
                f"\n[TX] ABORT "
                f"id=0x{transfer_id:08X} "
                f"cause=0x{cause:02X}"
            )

        except serial.SerialException:

            pass


    # ========================================================
    # PARSE START
    # ========================================================

    def _parse_start_payload(
        self,
        payload
    ):

        if len(payload) != 14:

            raise ValueError(
                "START debe tener "
                "14 bytes"
            )

        return {
            "transfer_id":
                int.from_bytes(
                    payload[0:4],
                    byteorder="big"
                ),

            "file_size":
                int.from_bytes(
                    payload[4:8],
                    byteorder="big"
                ),

            "file_type":
                payload[8],

            "baud_code":
                payload[9],

            "payload_size":
                int.from_bytes(
                    payload[10:12],
                    byteorder="big"
                ),

            "window_size":
                payload[12],

            "hamming_mode":
                payload[13]
        }


    # ========================================================
    # VALIDAR START
    # ========================================================

    def _validate_start(
        self,
        info
    ):

        if (
            info["baud_code"]
            != self._baud_code()
        ):
            return False

        if (
            info["payload_size"]
            != self.payload_size
        ):
            return False

        if (
            info["window_size"]
            != self.window_size
        ):
            return False

        expected_hamming = (
            0x01
            if self.hamming_enabled
            else 0x00
        )

        if (
            info["hamming_mode"]
            != expected_hamming
        ):
            return False

        if (
            info["file_type"]
            not in (
                FILE_TYPE_TXT,
                FILE_TYPE_PDF,
                FILE_TYPE_PNG
            )
        ):
            return False

        return True


    # ========================================================
    # BAUD CODE
    # ========================================================

    def _baud_code(self):

        if self.baud_rate == 9600:

            return BAUD_CODE_9600

        if self.baud_rate == 19200:

            return BAUD_CODE_19200

        raise ValueError(
            "Baud rate no soportado"
        )


    # ========================================================
    # FILE TYPE
    # ========================================================

    def _get_file_type(
        self,
        path
    ):

        extension = (
            Path(path)
            .suffix
            .lower()
        )

        if extension == ".txt":
            return FILE_TYPE_TXT

        if extension == ".pdf":
            return FILE_TYPE_PDF

        if extension == ".png":
            return FILE_TYPE_PNG

        raise ValueError(
            "Solo se permiten "
            "TXT, PDF y PNG"
        )


    # ========================================================
    # EXTENSION
    # ========================================================

    def _get_extension(
        self,
        file_type
    ):

        if file_type == FILE_TYPE_TXT:
            return ".txt"

        if file_type == FILE_TYPE_PDF:
            return ".pdf"

        if file_type == FILE_TYPE_PNG:
            return ".png"

        return ".bin"


    # ========================================================
    # RESET RX
    # ========================================================

    def _reset_rx_session(self):

        self.rx_session_active = False

        self.rx_transfer_id = None

        self.rx_expected_sequence = 0

        self.rx_expected_file_size = None

        self.rx_file_type = None

        self.rx_received_data.clear()


    # ========================================================
    # LIMPIAR COLAS TX
    # ========================================================

    def _clear_tx_queues(self):

        queues = (
            self.start_ack_queue,
            self.ack_queue,
            self.fin_ack_queue,
            self.abort_queue
        )

        for q in queues:

            while True:

                try:
                    q.get_nowait()

                except queue.Empty:
                    break


    # ========================================================
    # ABORT REMOTO
    # ========================================================

    def _get_remote_abort(self):

        try:

            return (
                self.abort_queue
                .get_nowait()
            )

        except queue.Empty:

            return None


    # ========================================================
    # TX CANCELADA
    # ========================================================

    def _tx_cancelled(self):

        return (
            self.tx_cancel_requested
            .is_set()
            or
            not self.running.is_set()
        )


    # ========================================================
    # DESCRIPCION ABORT
    # ========================================================

    def _abort_description(
        self,
        cause
    ):

        descriptions = {

            ABORT_START_TIMEOUT:
                "Timeout START",

            ABORT_DATA_RETRIES:
                "MAX_RETRIES DATA",

            ABORT_FIN_TIMEOUT:
                "Timeout FIN",

            ABORT_USER_CANCEL:
                "Cancelacion manual",

            ABORT_REMOTE_ERROR:
                "Error remoto"
        }

        return descriptions.get(
            cause,
            "Causa desconocida"
        )


    # ========================================================
    # STATUS
    # ========================================================

    def show_status(self):

        self.log()
        self.log("==============================")
        self.log("ESTADO DEL ENDPOINT")
        self.log("==============================")

        if self.tx_transfer_id is None:

            self.log(
                "TX: inactivo"
            )

        else:

            self.log(
                f"TX: activo "
                f"id=0x"
                f"{self.tx_transfer_id:08X}"
            )

        if self.rx_session_active:

            self.log(
                f"RX: activo "
                f"id=0x"
                f"{self.rx_transfer_id:08X}"
            )

            self.log(
                f"RX esperando seq="
                f"{self.rx_expected_sequence}"
            )

            self.log(
                f"RX bytes="
                f"{len(self.rx_received_data)}"
            )

        else:

            self.log(
                "RX: esperando START"
            )


# ============================================================
# INTERFAZ DE CONSOLA
# ============================================================

def command_loop(
    endpoint
):

    print()
    print(
        "Comandos:"
    )

    print(
        "  send <archivo>"
    )

    print(
        "  status"
    )

    print(
        "  cancel"
    )

    print(
        "  quit"
    )

    while endpoint.running.is_set():

        try:

            command = input(
                "\nendpoint> "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt
        ):

            print()

            break

        if not command:
            continue

        # ----------------------------------------------------
        # QUIT
        # ----------------------------------------------------

        if command.lower() in (
            "quit",
            "exit"
        ):

            break

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if command.lower() == "status":

            endpoint.show_status()

            continue

        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------

        if command.lower() == "cancel":

            endpoint.cancel_transmission()

            continue

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        if command.lower().startswith(
            "send "
        ):

            path = (
                command[5:]
                .strip()
            )

            if not path:

                print(
                    "Debe indicar un archivo."
                )

                continue

            # La transmisión corre en un hilo separado.
            #
            # De esta manera el hilo receptor sigue activo
            # y el endpoint puede recibir simultáneamente.

            if (
                endpoint.tx_thread
                is not None
                and
                endpoint.tx_thread.is_alive()
            ):

                print(
                    "Ya existe una "
                    "transmision activa."
                )

                continue

            endpoint.tx_thread = (
                threading.Thread(
                    target=endpoint.send_file,
                    args=(path,),
                    daemon=True
                )
            )

            endpoint.tx_thread.start()

            continue

        print(
            "Comando desconocido."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Endpoint Full Duplex "
            "para transferencia GBN"
        )
    )

    parser.add_argument(
        "--port",
        default=None,
        help="Puerto serial para la consola; omítelo para abrir la interfaz gráfica"
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        choices=[
            9600,
            19200
        ]
    )

    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW_SIZE,
        choices=[
            4,
            6,
            8
        ]
    )

    parser.add_argument(
        "--payload",
        type=int,
        default=DEFAULT_PAYLOAD_SIZE,
        choices=[
            500,
            900
        ]
    )

    parser.add_argument(
        "--hamming",
        action="store_true"
    )

    args = parser.parse_args()

    if args.port is None:
        root = tk.Tk()
        DUINOTransferApp(root)
        root.mainloop()
        return

    endpoint = Endpoint(
        port=args.port,
        baud_rate=args.baud,
        window_size=args.window,
        payload_size=args.payload,
        hamming_enabled=args.hamming
    )

    try:

        endpoint.open()

        command_loop(
            endpoint
        )

    except serial.SerialException as error:

        print(
            f"Error serial: {error}"
        )

    finally:

        endpoint.close()



class DUINOTransferApp:
    def __init__(self, root):
        self.root = root
        root.title("Transferencia de archivos con Arduino")
        root.geometry("820x780")
        root.minsize(780, 740)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.closing = False
        self.commands = queue.Queue()
        self.sending = False
        self.error = None
        self.selected_file = tk.StringVar()
        self.output_directory = tk.StringVar(value=str(Path.cwd() / "recibidos"))
        self.status = tk.StringVar(value="Selecciona un puerto para enviar o recibir archivos.")
        self.connection_status = tk.StringVar(value="Sin conexión")
        self.hamming_enabled = tk.BooleanVar(value=True)
        self._build()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self.poll)

    def _build(self):
        # Usamos los controles y colores normales de Tkinter.
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Transferencia de archivos con Arduino").pack(anchor="w")
        ttk.Label(main, textvariable=self.connection_status).pack(anchor="w", pady=(4, 10))

        # Cada parámetro ocupa una fila: etiqueta a la izquierda y valor a la derecha.
        settings = ttk.LabelFrame(main, text="Configuración", padding=8)
        settings.pack(fill="x")
        self.choices = []
        self.port = self._choice(settings, "Puerto serial", [], 0, editable=True)
        self.refresh_button = ttk.Button(settings, text="Actualizar puertos", command=self.refresh_ports)
        self.refresh_button.grid(row=0, column=2, padx=5)
        self.baud = self._choice(settings, "Velocidad (bps)", [9600, 19200], 1)
        self.payload = self._choice(settings, "Datos por trama (bytes)", [500, 900], 2)
        self.window = self._choice(settings, "Ventana (tramas)", [4, 6, 8], 3)
        self.timeout = self._choice(settings, "Espera de confirmación (ms)", [2000, 5000, 10000, 30000], 4)
        settings.columnconfigure(1, weight=1)
        self.hamming_check = ttk.Checkbutton(
            settings,
            text="Hamming SECDED (13,8) en la capa física",
            variable=self.hamming_enabled
        )
        self.hamming_check.grid(row=5, column=0, columnspan=3, sticky="w", pady=(5, 0))

        operations = ttk.Frame(main)
        operations.pack(fill="x", pady=10)
        operations.columnconfigure(0, weight=1)
        operations.columnconfigure(1, weight=1)
        send = ttk.LabelFrame(operations, text="Enviar archivo", padding=8)
        send.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        receive = ttk.LabelFrame(operations, text="Recibir archivos", padding=8)
        receive.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.file_entry = ttk.Entry(send, textvariable=self.selected_file)
        self.file_entry.pack(fill="x", pady=(0, 8))
        self.choose_button = ttk.Button(send, text="Elegir TXT, PDF o PNG", command=self.choose_file)
        self.choose_button.pack(anchor="w")
        self.send_button = ttk.Button(send, text="Enviar archivo", command=lambda: self.start("send"))
        self.send_button.pack(anchor="w", pady=(10, 0))
        self.output_entry = ttk.Entry(receive, textvariable=self.output_directory)
        self.output_entry.pack(fill="x", pady=(0, 8))
        self.folder_button = ttk.Button(receive, text="Elegir carpeta de destino", command=self.choose_directory)
        self.folder_button.pack(anchor="w")
        self.receive_button = ttk.Button(receive, text="Iniciar recepción", command=lambda: self.start("receive"))
        self.receive_button.pack(anchor="w", pady=(10, 0))

        progress = ttk.Frame(main)
        progress.pack(fill="x")
        self.progress_bars = {}
        self.percent_labels = {}
        for role, title in (("send", "Enviado"), ("receive", "Recibido")):
            row = ttk.Frame(progress)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=title, width=10).pack(side="left")
            bar = ttk.Progressbar(row, maximum=100)
            bar.pack(side="left", fill="x", expand=True, padx=10)
            percent = ttk.Label(row, text="0%", width=7, anchor="e")
            percent.pack(side="right")
            self.progress_bars[role] = bar
            self.percent_labels[role] = percent
        status_row = ttk.Frame(main)
        status_row.pack(fill="x", pady=(10, 12))
        ttk.Label(status_row, textvariable=self.status, wraplength=580).pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(status_row, text="Detener", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right")

        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True)
        logs = ttk.Frame(notebook, padding=8)
        frames = ttk.Frame(notebook, padding=8)
        files = ttk.Frame(notebook, padding=8)
        hamming = ttk.Frame(notebook, padding=8)
        notebook.add(logs, text="Registro de comunicación")
        notebook.add(frames, text="Tramas del protocolo")
        notebook.add(files, text="Archivos recibidos")
        notebook.add(hamming, text="Errores y correcciones Hamming")
        self.log = tk.Text(logs, state="disabled", wrap="word", height=8)
        scroll = ttk.Scrollbar(logs, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.frames = self._tree(frames, ("Hora", "Dirección", "Tipo", "SEQ", "ACK", "Bytes"))
        self.frames.bind("<<TreeviewSelect>>", self.show_frame)
        self.frame_details = tk.StringVar(value="Selecciona una trama para consultar sus bytes en hexadecimal.")
        ttk.Label(frames, textvariable=self.frame_details, wraplength=720).pack(fill="x", pady=(8, 0))
        self.raw_frames = {}
        self.files = self._tree(files, ("Archivo", "Bytes", "Verificación", "Ruta"))
        self.hamming_summary = tk.StringVar(
            value="Esperando estadísticas Hamming del Arduino…")
        ttk.Label(hamming, textvariable=self.hamming_summary).pack(anchor="w", pady=(0, 8))
        ttk.Label(hamming, text="Estadísticas de las tramas que este Arduino recibe por el enlace físico.").pack(
            anchor="w", pady=(0, 6))
        self.hamming_events = self._tree(
            hamming, ("Hora", "Trama", "Bloques", "Corregidos", "Paridad global",
                      "Errores dobles", "Último error", "Bloque error", "Posición", "Palabra"))
        self.hamming_counts = {"blocks": 0, "corrected": 0, "global": 0, "double": 0}

    def _choice(self, parent, label, values, row, editable=False):
        """Agrega una etiqueta y una lista de opciones a la configuración."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=5, pady=3)
        state = "readonly"
        if editable:
            state = "normal"
        choice = ttk.Combobox(parent, values=values, state=state)
        if values:
            choice.set(values[0])
        choice.grid(row=row, column=1, sticky="ew", padx=5, pady=3)
        self.choices.append(choice)
        return choice

    def _tree(self, parent, columns):
        area = ttk.Frame(parent)
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(area, columns=columns, show="headings", height=6)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=130 if column in ("Archivo", "Ruta") else 85, minwidth=50)
        scrollbar = ttk.Scrollbar(area, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = [item.device for item in list_ports.comports()]
            self.port["values"] = ports
            if not self.port.get() and ports:
                self.port.set(ports[0])
            self.write_log("Puertos detectados: " + (", ".join(ports) or "ninguno"))
        except ImportError:
            self.write_log("Instala pyserial con: python3 -m pip install -r gui/requirements.txt")

    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Seleccionar archivo PDF, TXT o PNG",
            filetypes=[
                ("PDF, TXT y PNG", ("*.pdf", "*.txt", "*.png")),
                ("PDF", "*.pdf"),
                ("TXT", "*.txt"),
                ("PNG", "*.png"),
            ],
        )
        if not path:
            return
        if Path(path).suffix.lower() not in (".pdf", ".txt", ".png"):
            messagebox.showwarning("Archivo no permitido", "Selecciona un archivo PDF, TXT o PNG.")
            return
        self.selected_file.set(path)

    def choose_directory(self):
        path = filedialog.askdirectory()
        if path:
            self.output_directory.set(path)

    def start(self, role):
        if self.closing or (self.stop.is_set() and self.worker and self.worker.is_alive()):
            return
        if role == "send" and self.sending:
            return
        try:
            if not self.port.get().strip():
                raise ValueError("Selecciona o escribe el puerto serial del Arduino.")
            config = {
                "PORT": self.port.get().strip(),
                "BAUD_RATE": int(self.baud.get()),
                "PAYLOAD_SIZE": int(self.payload.get()),
                "WINDOW_SIZE": int(self.window.get()),
                "TIMEOUT": int(self.timeout.get()) / 1000,
                "HAMMING_ENABLED": bool(self.hamming_enabled.get()),
            }
            if role == "send":
                path = Path(self.selected_file.get()).expanduser()
                if not path.is_file() or path.suffix.lower() not in (".txt", ".pdf", ".png"):
                    raise ValueError("Selecciona un archivo TXT, PDF o PNG existente.")
                config["FILE_PATH"] = str(path.resolve())
            if not self.output_directory.get().strip():
                raise ValueError("Selecciona una carpeta de destino.")
            folder = Path(self.output_directory.get()).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            config["OUTPUT_DIRECTORY"] = str(folder.resolve())
        except (ValueError, OSError) as error:
            messagebox.showwarning("Revisa la configuración", str(error))
            return
        if not self.worker or not self.worker.is_alive():
            self.error = None
            self.stop.clear()
            self.commands = queue.Queue()
            self.status.set("Abriendo puerto serial…")
            self.set_busy(True)
            self.worker = threading.Thread(target=self.run_endpoint, args=(config,), daemon=True)
            self.worker.start()
        if role == "send":
            self.sending = True
            self.send_button.configure(state="disabled")
            self.update_progress("send", 0, 0)
            self.commands.put(config["FILE_PATH"])

    def run_endpoint(self, config):
        """Los hilos usan la cola; solamente poll modifica la interfaz."""
        def emit(kind, **data):
            self.events.put((kind, data))

        endpoint = Endpoint(
            port=config["PORT"], baud_rate=config["BAUD_RATE"],
            window_size=config["WINDOW_SIZE"], payload_size=config["PAYLOAD_SIZE"],
            hamming_enabled=config["HAMMING_ENABLED"], timeout=config["TIMEOUT"],
            output_directory=config["OUTPUT_DIRECTORY"], on_event=emit,
        )
        try:
            endpoint.open()
            emit("connected", port=endpoint.port)
            while not self.stop.is_set() and endpoint.running.is_set():
                try:
                    path = self.commands.get(timeout=0.05)
                except queue.Empty:
                    continue
                endpoint.tx_thread = threading.Thread(
                    target=endpoint.send_file, args=(path,), daemon=True)
                endpoint.tx_thread.start()
            if not self.stop.is_set():
                emit("error", message="Se perdió la conexión serial.")
        except Exception as error:
            emit("error", message=str(error))
        finally:
            try:
                endpoint.close()
            finally:
                emit("done")

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.receive_button, self.refresh_button,
                       self.folder_button, self.output_entry, self.hamming_check):
            widget.configure(state=state)
        for widget in self.choices:
            if busy:
                widget.configure(state="disabled")
            elif widget is self.port:
                widget.configure(state="normal")
            else:
                widget.configure(state="readonly")
        self.send_button.configure(state="disabled" if self.sending else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def update_progress(self, role, current, total):
        percent = 0
        if total:
            percent = min(100, current * 100 / total)
        self.progress_bars[role]["value"] = percent
        self.percent_labels[role].configure(text=f"{percent:.0f}%")

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 3000:
            self.log.delete("1.0", "501.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_frame(self, _event):
        selection = self.frames.selection()
        if selection:
            raw = self.raw_frames.get(selection[0], "")
            self.frame_details.set(raw[:400] + (" … (trama completa en el registro)" if len(raw) > 400 else ""))

    def poll(self):
        for _ in range(200):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(kind, data)
        if self.closing and not (self.worker and self.worker.is_alive()) and self.events.empty():
            self.root.destroy()
            return
        self.root.after(50, self.poll)

    def handle_event(self, kind, data):
        if kind == "log":
            self.write_log(data["text"])
        elif kind == "connected":
            self.connection_status.set(f"Conectado · {data['port']}")
            self.status.set("Conectado. Puedes enviar y recibir archivos al mismo tiempo.")
        elif kind == "receiving":
            self.update_progress("receive", 0, data["total"])
            self.status.set(f"Recibiendo transferencia {data['transfer_id']:08X} · {data['total']} bytes")
        elif kind == "progress":
            self.update_progress(data["role"], data["current"], data["total"])
            self.status.set(f"{data['current']} / {data['total']} bytes · esperando verificación FIN / SHA-256")
        elif kind in ("sent", "received"):
            self.progress_bars[data["role"]]["value"] = 100
            self.percent_labels[data["role"]].configure(text="100%")
            self.status.set("Archivo verificado por SHA-256." + (" Esperando otro START…" if kind == "received" else ""))
            if kind == "received":
                self.files.insert("", 0, values=(Path(data["path"]).name, data["total"], "SHA-256 correcto", data["path"]))
        elif kind == "frame":
            item = self.frames.insert("", "end", values=(datetime.now().strftime("%H:%M:%S"), data["direction"],
                                                          data["name"], data["sequence"], data["ack"], data["size"]))
            self.raw_frames[item] = data["raw"]
            self.frames.see(item)
            self.write_log(f"{data['direction']} {data['name']} · {data['raw']}")
            if len(self.raw_frames) > 500:
                oldest = self.frames.get_children()[0]
                self.frames.delete(oldest)
                self.raw_frames.pop(oldest, None)
        elif kind == "hamming_stats":
            self.hamming_counts["blocks"] += data["blocks"]
            self.hamming_counts["corrected"] = data["total_corrected"]
            self.hamming_counts["global"] = data["total_global"]
            self.hamming_counts["double"] = data["total_double"]
            status_names = {0: "Sin error", 1: "Bit corregido", 2: "Paridad global", 3: "Doble error"}
            result = status_names.get(data["status"], "Desconocido")
            self.hamming_events.insert(
                "", "end", values=(datetime.now().strftime("%H:%M:%S"), data["frame_id"],
                                   data["blocks"], data["corrected"], data["global_parity"],
                                   data["double"], result,
                                   data["last_block"] if data["status"] else "—",
                                   data["position"] or "—",
                                   f"0x{data['word']:04X}" if data["status"] else "—"))
            children = self.hamming_events.get_children()
            if children:
                self.hamming_events.see(children[-1])
            if len(children) > 1000:
                self.hamming_events.delete(children[0])
            self.hamming_summary.set(
                f"Bloques: {self.hamming_counts['blocks']} · "
                f"Corregidos: {self.hamming_counts['corrected']} · "
                f"Paridad global: {self.hamming_counts['global']} · "
                f"Errores dobles: {self.hamming_counts['double']}")
            self.write_log(
                f"Hamming trama {data['frame_id']}: {data['corrected']} corregidos, "
                f"{data['global_parity']} de paridad global, {data['double']} dobles; "
                f"último estado: {result}")
        elif kind == "error":
            self.error = data["message"]
        elif kind == "rejected":
            self.status.set(data["message"])
        elif kind == "send_done":
            self.sending = False
            if not self.stop.is_set():
                self.send_button.configure(state="normal")
            if not data["completed"]:
                self.status.set("Envío detenido o fallido. Consulta el registro.")
        elif kind == "done":
            self.connection_status.set("Sin conexión · puerto cerrado")
            self.sending = False
            self.set_busy(False)
            if self.error:
                self.status.set(f"Error: {self.error}")
            else:
                self.status.set("Conexión cerrada.")

    def cancel(self):
        self.stop.set()
        self.cancel_button.configure(state="disabled")
        self.send_button.configure(state="disabled")
        self.status.set("Deteniendo la operación y cerrando el puerto…")

    def close(self):
        self.closing = True
        self.cancel()


if __name__ == "__main__":
    main()
