"""Demo sin Arduino: transferencia completa (START, Go-Back-N, FIN) sobre un cable simulado.

    uv run python -m redes_arduino.demo ARCHIVO [--baud 9600] [--payload 900] [--window 8]
                                                [--no-hamming] [--ber 0.0005] [--latency 0.05]
                                                [--both]
    uv run python -m redes_arduino.demo ARCHIVO --matrix resultados.csv [--ber ...]

El tiempo es simulado: la demo termina en segundos aunque la transferencia "dure" minutos.
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from .messages import FileType, Speed
from .monitor import LinkStats, status_lines
from .session import Endpoint, LinkConfig, SenderSession
from .simchannel import SimLink

FILE_TYPES = {".txt": FileType.TXT, ".pdf": FileType.PDF, ".png": FileType.PNG}
SPEEDS = {9600: Speed.BPS_9600, 19200: Speed.BPS_19200}


@dataclass
class Result:
    ok: bool
    seconds: float
    sender: SenderSession
    tx_stats: LinkStats  # terminal que envía
    rx_stats: LinkStats  # terminal que recibe
    received: bytes | None

    @property
    def throughput_bps(self) -> float:
        return 8 * len(self.sender.data) / self.seconds if self.ok and self.seconds else 0.0


def transfer(
    data: bytes,
    config: LinkConfig,
    ber: float = 0.0,
    seed: int = 1,
    latency: float = 0.0,
    file_type: FileType = FileType.PDF,
    both: bool = False,
    max_retries: int = 10,
    until: float = 24 * 3600,
) -> tuple[Result, Result | None]:
    """Envía `data` de A a B (y de B a A si `both`). Devuelve el resultado de cada sentido."""
    a, b = Endpoint("A", config), Endpoint("B", config)
    timeout = config.timeout(latency)
    sa = a.send_file(data, file_type, 1, timeout, max_retries)
    sb = b.send_file(data, file_type, 2, timeout, max_retries) if both else None
    link = SimLink(a, b, ber=ber, seed=seed, latency=latency)
    link.run(until)

    def result(s: SenderSession, tx: Endpoint, rx: Endpoint) -> Result:
        got = rx.receiver.data
        return Result(got == data, link.now, s, tx.stats, rx.stats, got)

    return result(sa, a, b), (result(sb, b, a) if sb else None)


def _print(title: str, r: Result) -> None:
    s = r.sender
    print(f"== {title}")
    for line in status_lines(s.phase, r.rx_stats, s.progress):
        print(f"   {line}")
    if s.error:
        print(f"   Causa: {s.error}")
    print(
        f"   Tiempo simulado: {r.seconds:.2f} s   Throughput útil: {r.throughput_bps:.0f} bps\n"
        f"   Tramas DATA enviadas: {r.tx_stats.data_frames_sent}   "
        f"retransmisiones: {r.tx_stats.retransmissions}   timeouts: {r.tx_stats.timeouts}\n"
        f"   Recepción: tramas OK {r.rx_stats.frames_received}, "
        f"dañadas {r.rx_stats.damaged_frames} "
        f"(framing {r.rx_stats.framing_errors}, checksum {r.rx_stats.checksum_errors}), "
        f"bloques Hamming corregidos {r.rx_stats.hamming_corrected}, "
        f"no corregibles {r.rx_stats.hamming_uncorrectable}"
    )


MATRIX_FIELDS = [
    "baud",
    "payload",
    "window",
    "hamming",
    "ber",
    "ok",
    "seconds",
    "throughput_bps",
    "data_frames_sent",
    "retransmissions",
    "timeouts",
    "damaged_frames",
    "hamming_corrected",
    "error_rate_pct",
]


def matrix(
    data: bytes, ber: float, seed: int, latency: float, file_type: FileType
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for baud, speed in SPEEDS.items():
        for payload in (500, 900):
            for window in (4, 6, 8):
                for ham in (True, False):
                    cfg = LinkConfig(speed, payload, window, ham)
                    r, _ = transfer(data, cfg, ber, seed, latency, file_type)
                    rows.append(
                        {
                            "baud": baud,
                            "payload": payload,
                            "window": window,
                            "hamming": int(ham),
                            "ber": ber,
                            "ok": int(r.ok),
                            "seconds": round(r.seconds, 2),
                            "throughput_bps": round(r.throughput_bps),
                            "data_frames_sent": r.tx_stats.data_frames_sent,
                            "retransmissions": r.tx_stats.retransmissions,
                            "timeouts": r.tx_stats.timeouts,
                            "damaged_frames": r.rx_stats.damaged_frames,
                            "hamming_corrected": r.rx_stats.hamming_corrected,
                            "error_rate_pct": round(r.rx_stats.error_rate, 2),
                        }
                    )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--baud", type=int, default=9600, choices=sorted(SPEEDS))
    ap.add_argument("--payload", type=int, default=900, choices=(500, 900))
    ap.add_argument("--window", type=int, default=8, choices=(4, 6, 8))
    ap.add_argument("--no-hamming", action="store_true")
    ap.add_argument("--ber", type=float, default=0.0, help="probabilidad de invertir cada bit")
    ap.add_argument("--latency", type=float, default=0.05, help="retardo USB+Arduino (s)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-retries", type=int, default=10)
    ap.add_argument("--both", action="store_true", help="transferir en ambos sentidos a la vez")
    ap.add_argument("--matrix", type=Path, metavar="CSV", help="correr las 24 combinaciones")
    args = ap.parse_args()

    data = args.file.read_bytes()
    file_type = FILE_TYPES.get(args.file.suffix.lower(), FileType.PDF)

    if args.matrix:
        rows = matrix(data, args.ber, args.seed, args.latency, file_type)
        with args.matrix.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MATRIX_FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} combinaciones -> {args.matrix}")
        sys.exit(0 if all(r["ok"] for r in rows) else 1)

    cfg = LinkConfig(SPEEDS[args.baud], args.payload, args.window, not args.no_hamming)
    print(
        f"Archivo: {args.file.name} ({len(data)} bytes)   {args.baud} bps, carga {args.payload} B, "
        f"ventana {args.window}, Hamming {'sí' if cfg.hamming else 'no'}, BER {args.ber}, "
        f"latencia {args.latency} s, timeout {cfg.timeout(args.latency):.2f} s"
    )
    ab, ba = transfer(
        data, cfg, args.ber, args.seed, args.latency, file_type, args.both, args.max_retries
    )
    _print("A -> B", ab)
    if ba:
        _print("B -> A", ba)
    sys.exit(0 if ab.ok and (ba is None or ba.ok) else 1)


if __name__ == "__main__":
    main()
