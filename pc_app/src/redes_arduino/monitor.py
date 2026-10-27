"""Estadísticas del enlace y mensajes de estado que pide la especificación."""

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    IDLE = "idle"
    STARTING = "starting"  # START enviado, esperando START_ACK
    TRANSFERRING = "transferring"  # Go-Back-N en curso
    FINISHING = "finishing"  # FIN enviado, esperando FIN_ACK
    DONE = "done"
    FAILED = "failed"


@dataclass
class LinkStats:
    """Contadores de una terminal. Lo recibido se mide en el lado que recibe."""

    frames_sent: int = 0
    data_frames_sent: int = 0
    retransmissions: int = 0
    timeouts: int = 0
    frames_received: int = 0  # tramas que pasaron todas las verificaciones
    framing_errors: int = 0  # escape inválido, Hamming doble, longitud rara
    checksum_errors: int = 0  # FrameError: checksum, longitud o tipo inválido
    hamming_blocks: int = 0
    hamming_corrected: int = 0
    hamming_uncorrectable: int = 0

    @property
    def damaged_frames(self) -> int:
        return self.framing_errors + self.checksum_errors

    @property
    def error_rate(self) -> float:
        """Tasa estimada de tramas con errores: dañadas / recibidas (en %)."""
        total = self.frames_received + self.damaged_frames
        return 100 * self.damaged_frames / total if total else 0.0


def status_lines(phase: Phase, stats: LinkStats, progress: float | None = None) -> list[str]:
    """Mensajes del monitor del enlace. `progress` en [0, 1]."""
    lines: list[str] = []
    if phase is Phase.STARTING:
        lines.append("Inicio de transmisión...")
    elif phase in (Phase.TRANSFERRING, Phase.FINISHING):
        lines.append("Transmisión en curso...")
    if stats.damaged_frames == 0 and stats.hamming_uncorrectable == 0:
        lines.append("Estado de enlace óptimo...")
    else:
        lines.append("Estado de enlace ruidoso...")
    if progress is not None:
        lines.append(f"Progreso: {100 * progress:.1f} %")
    if phase is Phase.DONE:
        lines.append("Transmisión Finalizada!")
    elif phase is Phase.FAILED:
        lines.append("Transmisión fallida")
    lines.append(f"Tasa de error estimada: {stats.error_rate:.2f} %")
    return lines
