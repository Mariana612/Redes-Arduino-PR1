"""Serial transport for the DUINO framed file-transfer protocol."""

import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pc_app" / "src"))

from redes_arduino.framing import Deframer, encode_physical  # noqa: E402
from redes_arduino.frame import decode  # noqa: E402
from redes_arduino.messages import FileType, Speed  # noqa: E402
from redes_arduino.monitor import Phase  # noqa: E402
from redes_arduino.session import Endpoint, LinkConfig  # noqa: E402


class SerialTransferWorker:
    """Owns serial I/O, config negotiation, and the Endpoint protocol state."""

    def __init__(self, serial_port, config, timeout_seconds, notify):
        self.serial = serial_port
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.notify = notify
        self.commands = queue.Queue()
        self.endpoint = Endpoint("GUI", config)
        self.deframer = Deframer(config.hamming)
        self.pending_token = None
        self.pending_deadline = None
        self.pending_file = None
        self.last_progress = 0.0
        self.ready_at = time.monotonic() + 2.0  # USB serial opening resets most Arduino boards.
        self._running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def check_config(self):
        self.commands.put(("check", None))

    def send_file(self, path, data, file_type):
        self.commands.put(("send", (path, data, file_type)))

    def update_config(self, config, timeout_seconds):
        self.commands.put(("config", (config, timeout_seconds)))

    def close(self):
        self._running = False
        try:
            self.serial.cancel_read()
        except (AttributeError, OSError):
            pass
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    @property
    def stopped(self):
        return not self.thread.is_alive()

    def _run(self):
        line = bytearray()
        in_frame = False
        while self._running:
            if time.monotonic() < self.ready_at:
                time.sleep(0.05)
                continue
            try:
                self._commands()
                if self.pending_deadline is not None and time.monotonic() >= self.pending_deadline:
                    self.pending_deadline = None
                    self.pending_token = None
                    self.pending_file = None
                    self.notify(
                        "error",
                        "No hubo respuesta al handshake. Verifica que ambas aplicaciones estén abiertas y que ambos Arduinos tengan cargados los sketches puente actualizados.",
                    )
                chunk = self.serial.read(1024)
            except Exception as exc:
                if self._running:
                    self.notify("error", f"Error de puerto serial: {exc}")
                break
            if not self._running:
                break
            for byte in chunk:
                if byte == 0x7E:
                    if in_frame:
                        for physical in self.deframer.feed(b"\x7e"):
                            if physical.valid:
                                self._receive_body(physical.body)
                        in_frame = False
                    else:
                        # Start a fresh physical frame; discard stale noise.
                        self.deframer.feed(b"\x7e")
                        in_frame = True
                    line.clear()
                elif in_frame:
                    for physical in self.deframer.feed(bytes((byte,))):
                        if physical.valid:
                            self._receive_body(physical.body)
                elif byte == 10:
                    self._receive_line(bytes(line).strip())
                    line.clear()
                elif byte != 13:
                    if len(line) < 256:
                        line.append(byte)
                    else:
                        line.clear()
            try:
                self._pump_protocol()
            except Exception as exc:
                if self._running:
                    self.notify("error", f"Error de transferencia serial: {exc}")
                break

    def _commands(self):
        while True:
            try:
                kind, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if kind == "check":
                if self._transfer_active():
                    self.notify("error", "Espera a que termine la transferencia activa antes de comprobar la configuración.")
                    continue
                self._start_config_check(None)
            elif kind == "send":
                if self._transfer_active():
                    self.notify("error", "Termina primero la transferencia que este equipo está recibiendo.")
                    continue
                self._start_config_check(value)
            elif kind == "config":
                if self._transfer_active():
                    self.notify("error", "No cambies la configuración mientras se recibe un archivo.")
                    continue
                self.config, self.timeout_seconds = value
                self.endpoint = Endpoint("GUI", self.config)
                self.deframer = Deframer(self.config.hamming)

    def _start_config_check(self, pending_file):
        self.pending_token = f"{time.monotonic_ns() & 0xffffffff:08X}"
        self.pending_file = pending_file
        self.pending_deadline = time.monotonic() + 5.0
        self._write_config_line("DUINO_CONFIG", self.pending_token)
        self.notify("status", "Verificando la configuración del otro equipo antes de enviar…")

    def _transfer_active(self):
        sender = self.endpoint.sender
        return (
            self.endpoint.receiver.phase is Phase.TRANSFERRING
            or (sender is not None and not sender.finished)
        )

    def _write_config_line(self, command, token):
        baud = self.config.speed.baud
        timeout_ms = int(self.timeout_seconds * 1000)
        line = f"{command}|{token}|{baud}|{self.config.payload_size}|{self.config.window}|{int(self.config.hamming)}|{timeout_ms}\n"
        self.serial.write(line.encode("ascii"))
        self.serial.flush()

    def _receive_line(self, raw):
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            return
        fields = text.split("|")
        if len(fields) != 7 or fields[0] not in ("DUINO_CONFIG", "DUINO_CONFIG_ACK"):
            return
        command, token = fields[:2]
        try:
            remote = LinkConfig(
                speed={9600: Speed.BPS_9600, 19200: Speed.BPS_19200}[int(fields[2])],
                payload_size=int(fields[3]),
                window=int(fields[4]),
                hamming=bool(int(fields[5])),
            )
            remote_timeout = int(fields[6]) / 1000
        except (ValueError, KeyError):
            return

        if command == "DUINO_CONFIG":
            self._write_config_line("DUINO_CONFIG_ACK", token)
            if remote == self.config and remote_timeout == self.timeout_seconds:
                self.notify("connected", "El enlace usa la misma configuración en ambos equipos.")
            else:
                self.notify("error", "El otro equipo tiene parámetros distintos; no se iniciará la transferencia.")
            return
        if token != self.pending_token:
            return

        self.pending_token = None
        self.pending_deadline = None
        if remote != self.config or remote_timeout != self.timeout_seconds:
            self.pending_file = None
            self.notify(
                "error",
                "Configuración incompatible: ambos equipos deben usar la misma velocidad, carga útil, ventana, Hamming y espera.",
            )
            return

        self.endpoint = Endpoint("GUI", self.config)
        self.deframer = Deframer(self.config.hamming)
        if self.pending_file is None:
            self.notify("connected", "Configuración confirmada en ambos equipos.")
            return

        path, data, file_type = self.pending_file
        self.pending_file = None
        transfer_id = time.monotonic_ns() & 0xFFFFFFFF
        self.endpoint.send_file(
            data,
            file_type,
            transfer_id,
            timeout=max(self.timeout_seconds, self.config.timeout()),
        )
        self.active_path = path
        self.active_data = data
        self.notify("status", f"Configuración confirmada. Iniciando {Path(path).name}…")

    def _receive_body(self, body):
        try:
            frame = decode(body)
        except ValueError:
            return
        before = self.endpoint.receiver.phase
        self.endpoint.on_frame(frame, time.monotonic())
        receiver = self.endpoint.receiver
        if receiver.phase is Phase.DONE and before is not Phase.DONE and receiver.data is not None:
            start = receiver.start
            self.notify("received", receiver.data, start.file_type.name.lower(), start.transfer_id)

    def _pump_protocol(self):
        now = time.monotonic()
        frame = self.endpoint.next_frame(now)
        if frame is not None:
            wire = encode_physical(frame.encode(), self.config.hamming)
            self._write_wire(wire)
            self.endpoint.on_transmitted(frame, time.monotonic())

        sender = self.endpoint.sender
        if sender is not None and sender.finished:
            if sender.phase is Phase.DONE:
                self.notify("sent", getattr(self, "active_path", "archivo"))
            else:
                self.notify("error", sender.error or "La transferencia no pudo completarse.")
            self.endpoint.sender = None

        if sender is not None and now - self.last_progress >= 0.15:
            self.last_progress = now
            self.notify("progress", sender.progress, self.endpoint.receiver.progress)
        elif self.endpoint.receiver.phase is Phase.TRANSFERRING and now - self.last_progress >= 0.15:
            self.last_progress = now
            self.notify("progress", 0.0, self.endpoint.receiver.progress)

    def _write_wire(self, wire):
        # Keep USB bursts within the slower SoftwareSerial receiver's buffer.
        chunk_size = 16
        for start in range(0, len(wire), chunk_size):
            if not self._running:
                return
            chunk = wire[start:start + chunk_size]
            self.serial.write(chunk)
            time.sleep(len(chunk) * 12 / self.config.speed.baud)
        self.serial.flush()
