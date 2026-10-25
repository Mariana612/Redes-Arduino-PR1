"""Go-Back-N para una dirección de la comunicación.

No hace E/S ni usa relojes propios: quien lo use pasa el tiempo actual `now`
(en segundos) y le pide la siguiente trama cuando el medio está libre.

Índices absolutos (0, 1, 2, ...) internamente; en las tramas viajan módulo 16.
"""

from collections.abc import Sequence

from .frame import CHECKSUM_LEN, HEADER_LEN, SEQ_MOD, Frame
from .messages import Ack

UART_BITS_PER_BYTE = 10  # 8N1: inicio + 8 datos + parada
ACK_PAYLOAD_LEN = 4
MAX_WINDOW = SEQ_MOD - 1


def wire_bytes(payload_len: int, use_hamming: bool) -> int:
    """Bytes en el cable para una trama (sin contar escapes, ~1 % extra en promedio)."""
    body = HEADER_LEN + payload_len + CHECKSUM_LEN
    return (2 * body if use_hamming else body) + 2  # + delimitadores


def frame_time(payload_len: int, baud: int, use_hamming: bool) -> float:
    return wire_bytes(payload_len, use_hamming) * UART_BITS_PER_BYTE / baud


def suggest_timeout(
    baud: int, payload: int, use_hamming: bool, processing: float = 0.05, safety: float = 1.5
) -> float:
    """Timeout inicial del emisor.

    El temporizador arranca cuando la trama base terminó de salir. Su ACK puede
    esperar detrás de una trama de datos en la dirección contraria (full duplex
    con dos transferencias) y luego viajar él mismo.
    """
    data = frame_time(payload, baud, use_hamming)
    ack = frame_time(ACK_PAYLOAD_LEN, baud, use_hamming)
    return (data + ack + processing) * safety


class GbnSender:
    def __init__(
        self,
        transfer_id: int,
        payloads: Sequence[bytes],
        window: int,
        timeout: float,
        max_retries: int = 10,
    ) -> None:
        if not 1 <= window <= MAX_WINDOW:
            raise ValueError(f"ventana inválida: {window} (1..{MAX_WINDOW})")
        self.transfer_id = transfer_id
        self.payloads = list(payloads)
        self.window = window
        self.timeout = timeout
        self.max_retries = max_retries

        self.base = 0  # trama más antigua sin confirmar
        self.next_new = 0  # primera trama nunca enviada
        self.cursor = 0  # próxima trama a poner en el cable
        self.deadline: float | None = None
        self.retries = 0  # vencimientos seguidos sin avance
        self.failed = False

        self.frames_sent = 0
        self.retransmissions = 0
        self.timeouts = 0

    @property
    def done(self) -> bool:
        return self.base == len(self.payloads)

    @property
    def outstanding(self) -> int:
        return self.cursor - self.base

    def _check_timer(self, now: float) -> None:
        if self.deadline is None or now < self.deadline:
            return
        self.deadline = None
        self.timeouts += 1
        self.retries += 1
        if self.retries > self.max_retries:
            self.failed = True
            return
        self.cursor = self.base  # go back N

    def next_frame(self, now: float) -> Frame | None:
        """Trama a transmitir ahora, o None si la ventana está llena / no hay nada."""
        if self.failed or self.done:
            return None
        self._check_timer(now)
        if self.failed:
            return None
        limit = min(len(self.payloads), self.base + self.window)
        if self.cursor >= limit:
            return None
        idx = self.cursor
        self.cursor += 1
        self.frames_sent += 1
        if idx < self.next_new:
            self.retransmissions += 1
        else:
            self.next_new = idx + 1
        return Frame.data(idx % SEQ_MOD, self.payloads[idx])

    def on_transmitted(self, seq: int, now: float) -> None:
        """La trama `seq` terminó de salir físicamente por el cable."""
        if self.deadline is None and self.base < self.cursor and seq == self.base % SEQ_MOD:
            self.deadline = now + self.timeout

    def on_ack(self, ack: Ack, now: float) -> bool:
        """Procesa un ACK acumulativo. Devuelve True si la ventana avanzó."""
        if ack.transfer_id != self.transfer_id or self.failed:
            return False
        advance = (ack.next_expected - self.base) % SEQ_MOD
        if not 1 <= advance <= self.next_new - self.base:
            return False  # duplicado o fuera de rango
        self.base += advance
        self.cursor = max(self.cursor, self.base)
        self.retries = 0
        self.deadline = now + self.timeout if self.base < self.cursor else None
        return True

    def next_deadline(self) -> float | None:
        return None if self.failed or self.done else self.deadline


class GbnReceiver:
    def __init__(self, transfer_id: int) -> None:
        self.transfer_id = transfer_id
        self.expected = 0  # índice absoluto
        self.payloads: list[bytes] = []
        self.discarded = 0  # duplicadas o fuera de orden

    @property
    def expected_seq(self) -> int:
        return self.expected % SEQ_MOD

    def on_data(self, fr: Frame) -> Frame:
        """Acepta la trama si es la esperada; siempre responde con el ACK acumulativo."""
        if fr.seq == self.expected_seq:
            self.payloads.append(fr.payload)
            self.expected += 1
        else:
            self.discarded += 1
        return Ack(self.transfer_id, self.expected_seq).to_frame()

    @property
    def received_bytes(self) -> int:
        return sum(len(p) for p in self.payloads)
