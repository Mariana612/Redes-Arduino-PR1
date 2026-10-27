from redes_arduino.monitor import LinkStats, Phase, status_lines


def test_optimal_link_messages() -> None:
    lines = status_lines(Phase.TRANSFERRING, LinkStats(frames_received=10), 0.5)
    assert lines == [
        "Transmisión en curso...",
        "Estado de enlace óptimo...",
        "Progreso: 50.0 %",
        "Tasa de error estimada: 0.00 %",
    ]


def test_noisy_link_and_rate() -> None:
    stats = LinkStats(frames_received=6, checksum_errors=1, framing_errors=1)
    assert stats.error_rate == 25.0
    lines = status_lines(Phase.DONE, stats)
    assert "Estado de enlace ruidoso..." in lines
    assert "Transmisión Finalizada!" in lines
    assert lines[-1] == "Tasa de error estimada: 25.00 %"


def test_starting_and_failed() -> None:
    assert status_lines(Phase.STARTING, LinkStats())[0] == "Inicio de transmisión..."
    assert "Transmisión fallida" in status_lines(Phase.FAILED, LinkStats())


def test_corrected_hamming_still_optimal() -> None:
    lines = status_lines(Phase.DONE, LinkStats(frames_received=3, hamming_corrected=5))
    assert "Estado de enlace óptimo..." in lines
