"""Demo sin Arduino: pasa un archivo por todas las capas sobre un canal con ruido.

    uv run python -m redes_arduino.demo ARCHIVO [--payload 900] [--no-hamming] [--ber 0.001]

No hay Go-Back-N todavía: las tramas descartadas se reenvían de inmediato hasta
que llegan bien (o se agotan los intentos), solo para ver el efecto del ruido.
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from . import frame, framing, packets
from .frame import Frame, FrameError
from .messages import FileType, Fin, Speed, Start


def flip_bits(data: bytes, ber: float, rng: random.Random) -> bytes:
    """Invierte cada bit con probabilidad `ber`. No toca los delimitadores 0x7E de los extremos."""
    if ber <= 0 or len(data) <= 2:
        return data
    out = bytearray(data)
    for i in range(1, len(out) - 1):
        for bit in range(8):
            if rng.random() < ber:
                out[i] ^= 1 << bit
    return bytes(out)


@dataclass
class Stats:
    frames_sent: int = 0
    frames_ok: int = 0
    hamming_corrected: int = 0
    hamming_uncorrectable: int = 0
    framing_errors: int = 0
    checksum_errors: int = 0
    retransmissions: int = 0

    @property
    def frame_error_rate(self) -> float:
        return (
            100 * (self.frames_sent - self.frames_ok) / self.frames_sent if self.frames_sent else 0
        )


def send(
    fr: Frame, use_hamming: bool, ber: float, rng: random.Random, stats: Stats
) -> Frame | None:
    """Envía una trama por el canal; devuelve la recibida o None si se descartó."""
    wire = flip_bits(framing.encode_physical(fr.encode(), use_hamming), ber, rng)
    stats.frames_sent += 1
    received = list(framing.Deframer(use_hamming).feed(wire))
    if len(received) != 1:
        # El ruido creó o rompió delimitadores
        stats.framing_errors += 1
        return None
    pf = received[0]
    if pf.stats:
        stats.hamming_corrected += pf.stats.corrected
        stats.hamming_uncorrectable += pf.stats.uncorrectable
    if not pf.valid:
        stats.framing_errors += 1
        return None
    try:
        decoded = frame.decode(pf.body)
    except FrameError:
        stats.checksum_errors += 1
        return None
    stats.frames_ok += 1
    return decoded


class _GiveUp(Exception):
    pass


def run(
    data: bytes, payload: int, use_hamming: bool, ber: float, seed: int, max_tries: int = 50
) -> tuple[bytes | None, Stats]:
    """Devuelve (archivo reconstruido, estadísticas); None si una trama agotó los intentos."""
    rng = random.Random(seed)
    stats = Stats()

    def deliver(fr: Frame) -> Frame:
        for attempt in range(max_tries):
            got = send(fr, use_hamming, ber, rng, stats)
            if got is not None:
                return got
            if attempt + 1 < max_tries:
                stats.retransmissions += 1
        raise _GiveUp

    try:
        start = Start(1, len(data), FileType.PDF, Speed.BPS_9600, payload, 8, use_hamming)
        deliver(start.to_frame())
        received = [
            deliver(Frame.data(i % frame.SEQ_MOD, p)).payload
            for i, p in enumerate(packets.split(data, payload))
        ]
        fin = Fin.from_payload(deliver(Fin(1, packets.sha256(data)).to_frame()).payload)
    except _GiveUp:
        return None, stats
    rebuilt = packets.reassemble(received)
    if packets.sha256(rebuilt) != fin.sha256:
        print("¡SHA-256 no coincide! (un error escapó al Checksum)", file=sys.stderr)
    return rebuilt, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--payload", type=int, default=900, choices=(500, 900))
    ap.add_argument("--no-hamming", action="store_true")
    ap.add_argument("--ber", type=float, default=0.0, help="probabilidad de invertir cada bit")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-tries", type=int, default=50, help="intentos por trama")
    args = ap.parse_args()

    data = args.file.read_bytes()
    use_hamming = not args.no_hamming
    rebuilt, s = run(data, args.payload, use_hamming, args.ber, args.seed, args.max_tries)

    print(f"Archivo:              {args.file.name} ({len(data)} bytes)")
    print(f"Hamming:              {'sí' if use_hamming else 'no'}   BER: {args.ber}")
    print(f"Tramas enviadas:      {s.frames_sent}  (retransmisiones: {s.retransmissions})")
    print(f"Bloques corregidos:   {s.hamming_corrected}")
    print(f"Bloques no corregib.: {s.hamming_uncorrectable}")
    print(f"Errores de framing:   {s.framing_errors}")
    print(f"Errores de checksum:  {s.checksum_errors}")
    print(f"Tasa de error estimada: {s.frame_error_rate:.2f} %")
    if rebuilt is None:
        print(f"Estado de enlace ruidoso... una trama no llegó tras {args.max_tries} intentos")
    elif s.frames_sent == s.frames_ok:
        print("Estado de enlace óptimo...")
    ok = rebuilt == data
    print("Transmisión Finalizada!" if ok else "Transferencia FALLIDA")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
