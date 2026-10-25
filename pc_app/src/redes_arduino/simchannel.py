"""Cable full duplex simulado, con reloj virtual y ruido.

Cada dirección (A->B y B->A) transmite una trama a la vez, en orden, y tarda
`bytes_en_cable * 10 / baud` segundos (UART 8N1). El ruido invierte bits al azar
en todo el flujo, delimitadores incluidos. El receptor usa el mismo `Deframer`
y `frame.decode` que usará con el Arduino real.

`latency` suma un retardo fijo entre que la trama termina de salir y que la PC
receptora la procesa (en el sistema real: USB + Arduino). Es lo que hace que el
ancho de ventana importe.

No modela: ruido en ráfagas ni diferencias de reloj entre los UART.
"""

import heapq
import itertools
import random
from collections.abc import Callable
from dataclasses import dataclass

from . import frame, framing
from .frame import Frame, FrameError
from .gbn import UART_BITS_PER_BYTE
from .session import Endpoint

MAX_STEPS_SAME_TIME = 10_000


def flip_bits(data: bytes, ber: float, rng: random.Random) -> bytes:
    """Invierte cada bit con probabilidad `ber`."""
    if ber <= 0:
        return data
    out = bytearray(data)
    for i in range(len(out)):
        for bit in range(8):
            if rng.random() < ber:
                out[i] ^= 1 << bit
    return bytes(out)


@dataclass
class _Direction:
    src: Endpoint
    dst: Endpoint
    deframer: framing.Deframer
    frame: Frame | None = None
    wire: bytes = b""
    finish: float = 0.0
    bytes_on_wire: int = 0
    busy_time: float = 0.0


class SimLink:
    def __init__(
        self,
        a: Endpoint,
        b: Endpoint,
        ber: float = 0.0,
        seed: int = 0,
        latency: float = 0.0,
        drop: Callable[[str, Frame], bool] | None = None,
    ) -> None:
        """`drop(nombre_origen, trama)` -> True pierde esa trama entera (para tests)."""
        self.a, self.b = a, b
        self.ber = ber
        self.latency = latency
        self.drop = drop
        self.rng = random.Random(seed)
        self.now = 0.0
        self.dirs = (
            _Direction(a, b, framing.Deframer(b.config.hamming)),
            _Direction(b, a, framing.Deframer(a.config.hamming)),
        )
        # (hora de llegada, desempate, dirección, bytes recibidos)
        self._arrivals: list[tuple[float, int, int, bytes]] = []
        self._tie = itertools.count()

    def _start(self, d: _Direction, fr: Frame) -> None:
        wire = framing.encode_physical(fr.encode(), d.src.config.hamming)
        duration = len(wire) * UART_BITS_PER_BYTE / d.src.config.speed.baud
        d.frame = fr
        lost = self.drop is not None and self.drop(d.src.name, fr)
        d.wire = b"" if lost else flip_bits(wire, self.ber, self.rng)
        d.finish = self.now + duration
        d.bytes_on_wire += len(wire)
        d.busy_time += duration

    def _complete(self, i: int) -> None:
        d = self.dirs[i]
        fr, d.frame = d.frame, None
        assert fr is not None
        d.src.on_transmitted(fr, self.now)
        heapq.heappush(self._arrivals, (self.now + self.latency, next(self._tie), i, d.wire))

    def _deliver(self, i: int, wire: bytes) -> None:
        d = self.dirs[i]
        stats = d.dst.stats
        for pf in d.deframer.feed(wire):
            if pf.stats is not None:
                stats.hamming_blocks += pf.stats.blocks
                stats.hamming_corrected += pf.stats.corrected
                stats.hamming_uncorrectable += pf.stats.uncorrectable
            if not pf.valid:
                stats.framing_errors += 1
                continue
            try:
                received = frame.decode(pf.body)
            except FrameError:
                stats.checksum_errors += 1
                continue
            d.dst.on_frame(received, self.now)

    def run(self, until: float = 3600.0) -> bool:
        """Simula hasta que ambas terminales terminan (True) o hasta `until` (False)."""
        same_time_steps = 0
        try:
            while True:
                for d in self.dirs:
                    if d.frame is None:
                        fr = d.src.next_frame(self.now)
                        if fr is not None:
                            self._start(d, fr)

                candidates = [d.finish for d in self.dirs if d.frame is not None]
                if self._arrivals:
                    candidates.append(self._arrivals[0][0])
                for d in self.dirs:
                    if d.frame is None:
                        dl = d.src.next_deadline()
                        if dl is not None:
                            candidates.append(max(dl, self.now))
                if not candidates:
                    return not (self.a.busy or self.b.busy)

                t = min(candidates)
                if t > until:
                    self.now = until
                    return False
                same_time_steps = same_time_steps + 1 if t == self.now else 0
                if same_time_steps > MAX_STEPS_SAME_TIME:
                    raise RuntimeError("la simulación no avanza (bug en una máquina de estados)")
                self.now = t
                for i, d in enumerate(self.dirs):
                    if d.frame is not None and d.finish <= self.now:
                        self._complete(i)
                while self._arrivals and self._arrivals[0][0] <= self.now:
                    _, _, i, wire = heapq.heappop(self._arrivals)
                    self._deliver(i, wire)
        finally:
            self.a.sync_stats()
            self.b.sync_stats()
