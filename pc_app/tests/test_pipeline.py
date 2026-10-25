import random

import pytest

from redes_arduino import demo


@pytest.mark.parametrize("use_hamming", [True, False])
@pytest.mark.parametrize("payload", [500, 900])
def test_clean_channel(use_hamming: bool, payload: int) -> None:
    data = random.Random(0).randbytes(5_000)
    rebuilt, stats = demo.run(data, payload, use_hamming, ber=0.0, seed=0)
    assert rebuilt == data
    assert stats.retransmissions == 0


def test_noisy_channel_hamming_corrects() -> None:
    data = random.Random(1).randbytes(3_000)
    rebuilt, stats = demo.run(data, 500, True, ber=1e-4, seed=1)
    assert rebuilt == data
    assert stats.hamming_corrected > 0


def test_noisy_channel_without_hamming_retransmits() -> None:
    data = random.Random(2).randbytes(3_000)
    rebuilt, stats = demo.run(data, 500, False, ber=1e-4, seed=2)
    assert rebuilt == data
    assert stats.retransmissions > 0


def test_gives_up_on_very_noisy_channel() -> None:
    data = random.Random(3).randbytes(2_000)
    rebuilt, stats = demo.run(data, 900, False, ber=0.01, seed=3, max_tries=3)
    assert rebuilt is None
    assert stats.frames_ok < stats.frames_sent
