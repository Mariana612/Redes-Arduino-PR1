import csv
import random
import sys
from pathlib import Path

import pytest

from redes_arduino import demo
from redes_arduino.session import LinkConfig


def test_cli_single_transfer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "foto.png"
    f.write_bytes(random.Random(0).randbytes(3_000))
    monkeypatch.setattr(sys, "argv", ["demo", str(f), "--ber", "0.0005", "--both"])
    with pytest.raises(SystemExit) as exc:
        demo.main()
    assert exc.value.code == 0


def test_cli_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "nota.txt"
    f.write_bytes(b"hola " * 300)
    out = tmp_path / "m.csv"
    monkeypatch.setattr(sys, "argv", ["demo", str(f), "--matrix", str(out)])
    with pytest.raises(SystemExit) as exc:
        demo.main()
    assert exc.value.code == 0
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 24
    assert {(r["baud"], r["payload"], r["window"], r["hamming"]) for r in rows} == {
        (b, p, w, h)
        for b in ("9600", "19200")
        for p in ("500", "900")
        for w in ("4", "6", "8")
        for h in ("0", "1")
    }


def test_noisy_channel_hamming_reduces_retransmissions() -> None:
    data = random.Random(1).randbytes(6_000)
    cfg_h = LinkConfig(payload_size=500, hamming=True)
    cfg_n = LinkConfig(payload_size=500, hamming=False)
    with_h, _ = demo.transfer(data, cfg_h, ber=5e-4, seed=3)
    without, _ = demo.transfer(data, cfg_n, ber=5e-4, seed=3)
    assert with_h.ok
    assert with_h.rx_stats.hamming_corrected > 0
    assert with_h.tx_stats.retransmissions < without.tx_stats.retransmissions
