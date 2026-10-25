import random

import pytest

from redes_arduino import demo
from redes_arduino.messages import Speed
from redes_arduino.monitor import Phase
from redes_arduino.session import LinkConfig
from redes_arduino.simchannel import flip_bits

DATA = random.Random(9).randbytes(4_000)


def test_flip_bits() -> None:
    rng = random.Random(0)
    assert flip_bits(b"\x00\xff", 0.0, rng) == b"\x00\xff"
    assert flip_bits(b"\x00\xff", 1.0, rng) == b"\xff\x00"


def test_time_scales_with_baud() -> None:
    slow, _ = demo.transfer(DATA, LinkConfig(Speed.BPS_9600))
    fast, _ = demo.transfer(DATA, LinkConfig(Speed.BPS_19200))
    assert slow.ok and fast.ok
    assert slow.seconds / fast.seconds == pytest.approx(2.0, rel=0.01)


def test_hamming_doubles_wire_time() -> None:
    ham, _ = demo.transfer(DATA, LinkConfig(hamming=True))
    raw, _ = demo.transfer(DATA, LinkConfig(hamming=False))
    assert ham.seconds / raw.seconds == pytest.approx(2.0, rel=0.05)


def test_full_duplex_both_directions_at_once() -> None:
    single, _ = demo.transfer(DATA, LinkConfig())
    ab, ba = demo.transfer(DATA, LinkConfig(), both=True)
    assert ba is not None
    assert ab.ok and ba.ok
    # en paralelo, no en serie: tarda poco más que una sola transferencia
    assert ab.seconds < 1.3 * single.seconds


def test_bigger_window_is_faster_with_latency() -> None:
    cfg4 = LinkConfig(Speed.BPS_19200, 500, 4, True)
    cfg8 = LinkConfig(Speed.BPS_19200, 500, 8, True)
    w4, _ = demo.transfer(DATA, cfg4, latency=1.0)
    w8, _ = demo.transfer(DATA, cfg8, latency=1.0)
    assert w4.ok and w8.ok
    assert w8.seconds < w4.seconds


@pytest.mark.parametrize("hamming", [True, False])
@pytest.mark.parametrize("seed", range(15))
def test_never_accepts_corrupted_file(hamming: bool, seed: int) -> None:
    data = random.Random(seed).randbytes(1_500)
    r, _ = demo.transfer(data, LinkConfig(payload_size=500, hamming=hamming), ber=2e-3, seed=seed)
    if r.sender.phase is Phase.DONE:
        assert r.received == data
    else:
        assert r.sender.phase is Phase.FAILED
        assert r.received is None
