import hashlib

import pytest

from redes_arduino import packets


@pytest.mark.parametrize("size", [500, 900])
def test_split_sizes(size: int) -> None:
    data = bytes(2 * size + 7)
    parts = packets.split(data, size)
    assert [len(p) for p in parts] == [size, size, 7]
    assert packets.reassemble(parts) == data


def test_split_exact_and_empty() -> None:
    assert [len(p) for p in packets.split(bytes(1000), 500)] == [500, 500]
    assert packets.split(b"", 500) == []


def test_split_rejects_other_sizes() -> None:
    with pytest.raises(ValueError):
        packets.split(b"abc", 512)


def test_sha256() -> None:
    assert packets.sha256(b"abc") == hashlib.sha256(b"abc").digest()
