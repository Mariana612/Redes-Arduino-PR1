"""Transferencia completa: START -> DATA (Go-Back-N) -> FIN, y la terminal full duplex.

Igual que `gbn`, no hace E/S: el medio pide tramas con `next_frame(now)`,
avisa con `on_transmitted` y entrega lo recibido con `on_frame`.
"""

from dataclasses import dataclass

from . import packets
from .frame import Frame, FrameError, FrameType
from .gbn import GbnReceiver, GbnSender, suggest_timeout
from .messages import (
    Abort,
    AbortReason,
    Ack,
    FileType,
    Fin,
    FinAck,
    FinStatus,
    Speed,
    Start,
    StartAck,
    StartStatus,
)
from .monitor import LinkStats, Phase


@dataclass(frozen=True)
class LinkConfig:
    """Parámetros que ambas terminales deben tener iguales."""

    speed: Speed = Speed.BPS_9600
    payload_size: int = 900
    window: int = 8
    hamming: bool = True

    def timeout(self, latency: float = 0.0) -> float:
        """Timeout sugerido; `latency` es el retardo de ida (USB + Arduino) por trama."""
        return suggest_timeout(
            self.speed.baud, self.payload_size, self.hamming, processing=0.05 + 2 * latency
        )

    def matches(self, start: Start) -> bool:
        return (
            start.speed is self.speed
            and start.payload_size == self.payload_size
            and start.window == self.window
            and start.hamming == self.hamming
        )


class SenderSession:
    def __init__(
        self,
        transfer_id: int,
        data: bytes,
        file_type: FileType,
        config: LinkConfig,
        timeout: float | None = None,
        max_retries: int = 10,
    ) -> None:
        self.transfer_id = transfer_id
        self.data = data
        self.config = config
        self.timeout = config.timeout() if timeout is None else timeout
        self.max_retries = max_retries
        self.phase = Phase.STARTING
        self.error: str | None = None

        self._start = Start(
            transfer_id,
            len(data),
            file_type,
            config.speed,
            config.payload_size,
            config.window,
            config.hamming,
        ).to_frame()
        self._fin = Fin(transfer_id, packets.sha256(data)).to_frame()
        self.gbn = GbnSender(
            transfer_id,
            packets.split(data, config.payload_size),
            config.window,
            self.timeout,
            max_retries,
        )
        # Temporizador de START/FIN: None = toca enviar; inf = enviado, aún saliendo
        self._ctrl_deadline: float | None = None
        self._ctrl_tries = 0
        self._abort_pending = False
        self._abort_reason: AbortReason | None = None
        self.control_retransmissions = 0

    # -- estado -----------------------------------------------------------------
    @property
    def progress(self) -> float:
        total = len(self.gbn.payloads)
        if self.phase is Phase.DONE:
            return 1.0
        return self.gbn.base / total if total else 0.0

    @property
    def finished(self) -> bool:
        return self.phase in (Phase.DONE, Phase.FAILED) and not self._abort_pending

    def _fail(self, reason: str, abort: AbortReason | None = None) -> None:
        self.phase = Phase.FAILED
        self.error = reason
        self._abort_pending = abort is not None
        self._abort_reason = abort

    # -- medio --------------------------------------------------------------------
    def _control_frame(self, fr: Frame, now: float) -> Frame | None:
        if self._ctrl_deadline is not None and now < self._ctrl_deadline:
            return None
        if self._ctrl_tries > self.max_retries:
            self._fail(f"{fr.type.name} sin respuesta", AbortReason.MAX_RETRIES)
            return self.next_frame(now)
        if self._ctrl_tries:
            self.control_retransmissions += 1
        self._ctrl_tries += 1
        self._ctrl_deadline = float("inf")
        return fr

    def next_frame(self, now: float) -> Frame | None:
        if self.phase is Phase.FAILED:
            if self._abort_pending:
                self._abort_pending = False
                assert self._abort_reason is not None
                return Abort(self.transfer_id, self._abort_reason).to_frame()
            return None
        if self.phase is Phase.STARTING:
            return self._control_frame(self._start, now)
        if self.phase is Phase.TRANSFERRING:
            fr = self.gbn.next_frame(now)
            if self.gbn.failed:
                self._fail("Go-Back-N agotó los reintentos", AbortReason.MAX_RETRIES)
                return self.next_frame(now)
            if fr is None and self.gbn.done:
                self._enter_finishing()
                return self.next_frame(now)
            return fr
        if self.phase is Phase.FINISHING:
            return self._control_frame(self._fin, now)
        return None

    def _enter_finishing(self) -> None:
        self.phase = Phase.FINISHING
        self._ctrl_deadline = None
        self._ctrl_tries = 0

    def on_transmitted(self, fr: Frame, now: float) -> None:
        if fr.type is FrameType.DATA:
            self.gbn.on_transmitted(fr.seq, now)
        elif fr.type in (FrameType.START, FrameType.FIN) and self._ctrl_deadline == float("inf"):
            self._ctrl_deadline = now + self.timeout

    def on_frame(self, fr: Frame, now: float) -> None:
        try:
            if fr.type is FrameType.START_ACK and self.phase is Phase.STARTING:
                sa = StartAck.from_payload(fr.payload)
                if sa.transfer_id != self.transfer_id:
                    return
                if sa.status is StartStatus.ACCEPTED:
                    self.phase = Phase.TRANSFERRING
                    self._ctrl_deadline = None
                else:
                    self._fail(f"START rechazado: {sa.status.name}")
            elif fr.type is FrameType.ACK and self.phase is Phase.TRANSFERRING:
                self.gbn.on_ack(Ack.from_frame(fr), now)
            elif fr.type is FrameType.FIN_ACK and self.phase is Phase.FINISHING:
                fa = FinAck.from_payload(fr.payload)
                if fa.transfer_id != self.transfer_id:
                    return
                if fa.status is FinStatus.OK:
                    self.phase = Phase.DONE
                else:
                    self._fail(f"FIN rechazado: {fa.status.name}")
        except FrameError:
            pass  # carga de control mal formada: se ignora

    def next_deadline(self) -> float | None:
        if self._abort_pending:
            return 0.0
        if self.phase in (Phase.STARTING, Phase.FINISHING):
            d = self._ctrl_deadline
            return 0.0 if d is None else (None if d == float("inf") else d)
        if self.phase is Phase.TRANSFERRING:
            return self.gbn.next_deadline()
        return None


class ReceiverSession:
    def __init__(self, config: LinkConfig) -> None:
        self.config = config
        self.phase = Phase.IDLE
        self.error: str | None = None
        self.start: Start | None = None
        self.gbn: GbnReceiver | None = None
        self.data: bytes | None = None
        self._start_reply: Frame | None = None
        self._fin_reply: Frame | None = None

    @property
    def progress(self) -> float:
        if self.start is None or self.gbn is None:
            return 0.0
        return self.gbn.received_bytes / self.start.file_size if self.start.file_size else 1.0

    def on_frame(self, fr: Frame) -> Frame | None:
        """Procesa una trama y devuelve la respuesta, si corresponde."""
        try:
            if fr.type is FrameType.START:
                return self._on_start(Start.from_payload(fr.payload))
            if fr.type is FrameType.DATA:
                return self.gbn.on_data(fr) if self.gbn else None
            if fr.type is FrameType.FIN:
                return self._on_fin(Fin.from_payload(fr.payload))
            if fr.type is FrameType.ABORT:
                ab = Abort.from_payload(fr.payload)
                if self.start and ab.transfer_id == self.start.transfer_id:
                    self.phase = Phase.FAILED
                    self.error = f"ABORT recibido: {ab.reason.name}"
        except FrameError:
            pass
        return None

    def _on_start(self, st: Start) -> Frame:
        if self.start is not None and st.transfer_id == self.start.transfer_id:
            assert self._start_reply is not None
            return self._start_reply  # START repetido: misma respuesta
        if self.phase in (Phase.STARTING, Phase.TRANSFERRING):
            return StartAck(st.transfer_id, StartStatus.BUSY).to_frame()
        if not self.config.matches(st):
            return StartAck(st.transfer_id, StartStatus.INCOMPATIBLE_PARAMS).to_frame()
        self.start = st
        self.gbn = GbnReceiver(st.transfer_id)
        self.data = None
        self.phase = Phase.TRANSFERRING
        self._fin_reply = None
        self._start_reply = StartAck(st.transfer_id, StartStatus.ACCEPTED).to_frame()
        return self._start_reply

    def _on_fin(self, fin: Fin) -> Frame | None:
        if self.start is None or self.gbn is None or fin.transfer_id != self.start.transfer_id:
            return None
        if self._fin_reply is not None:
            return self._fin_reply  # FIN repetido: no se reprocesa
        rebuilt = packets.reassemble(self.gbn.payloads)
        if len(rebuilt) != self.start.file_size:
            status = FinStatus.SIZE_MISMATCH
        elif packets.sha256(rebuilt) != fin.sha256:
            status = FinStatus.HASH_MISMATCH
        else:
            status = FinStatus.OK
        if status is FinStatus.OK:
            self.phase = Phase.DONE
            self.data = rebuilt
        else:
            self.phase = Phase.FAILED
            self.error = f"verificación final: {status.name}"
        self._fin_reply = FinAck(fin.transfer_id, status).to_frame()
        return self._fin_reply


class Endpoint:
    """Una terminal (PC + Arduino): puede enviar y recibir a la vez."""

    def __init__(self, name: str, config: LinkConfig) -> None:
        self.name = name
        self.config = config
        self.stats = LinkStats()
        self.sender: SenderSession | None = None
        self.receiver = ReceiverSession(config)
        self._replies: list[Frame] = []

    def send_file(
        self,
        data: bytes,
        file_type: FileType,
        transfer_id: int,
        timeout: float | None = None,
        max_retries: int = 10,
    ) -> SenderSession:
        self.sender = SenderSession(transfer_id, data, file_type, self.config, timeout, max_retries)
        return self.sender

    def _queue_reply(self, fr: Frame) -> None:
        if fr.type is FrameType.ACK:
            # El ACK es acumulativo: alcanza con mandar el más reciente.
            self._replies = [r for r in self._replies if r.type is not FrameType.ACK]
        self._replies.append(fr)

    def next_frame(self, now: float) -> Frame | None:
        """Primero las respuestas (ACK, START_ACK, FIN_ACK), después lo propio."""
        fr = self._replies.pop(0) if self._replies else None
        if fr is None and self.sender is not None:
            fr = self.sender.next_frame(now)
        if fr is not None:
            self.stats.frames_sent += 1
            if fr.type is FrameType.DATA:
                self.stats.data_frames_sent += 1
        return fr

    def on_transmitted(self, fr: Frame, now: float) -> None:
        if self.sender is not None:
            self.sender.on_transmitted(fr, now)

    def on_frame(self, fr: Frame, now: float) -> None:
        self.stats.frames_received += 1
        if fr.type in (FrameType.START_ACK, FrameType.ACK, FrameType.FIN_ACK):
            if self.sender is not None:
                self.sender.on_frame(fr, now)
        else:
            reply = self.receiver.on_frame(fr)
            if reply is not None:
                self._queue_reply(reply)

    def next_deadline(self) -> float | None:
        if self._replies:
            return 0.0
        return self.sender.next_deadline() if self.sender else None

    def sync_stats(self) -> None:
        """Copia los contadores del emisor Go-Back-N a `stats`."""
        if self.sender is not None:
            s = self.sender
            self.stats.retransmissions = s.gbn.retransmissions + s.control_retransmissions
            self.stats.timeouts = s.gbn.timeouts

    @property
    def busy(self) -> bool:
        return bool(self._replies) or (self.sender is not None and not self.sender.finished)
