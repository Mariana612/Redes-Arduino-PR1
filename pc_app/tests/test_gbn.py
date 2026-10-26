import pytest

from redes_arduino.frame import Frame
from redes_arduino.gbn import GbnReceiver, GbnSender, frame_time, suggest_timeout
from redes_arduino.messages import Ack


def mk(n: int = 20, window: int = 4, timeout: float = 1.0, max_retries: int = 3) -> GbnSender:
    return GbnSender(7, [bytes([i]) for i in range(n)], window, timeout, max_retries)


def drain(s: GbnSender, now: float) -> list[Frame]:
    out = []
    while (f := s.next_frame(now)) is not None:
        out.append(f)
    return out


def ack(n: int) -> Ack:
    return Ack(7, n)


def test_window_limits_outstanding_frames() -> None:
    s = mk(window=4)
    assert [f.seq for f in drain(s, 0)] == [0, 1, 2, 3]
    assert s.next_frame(0) is None
    assert s.on_ack(ack(2), 0)
    assert [f.seq for f in drain(s, 0)] == [4, 5]


@pytest.mark.parametrize("window", [4, 6, 8])
def test_full_transfer_wraps_sequence_numbers(window: int) -> None:
    s, r = mk(n=40, window=window), GbnReceiver(7)
    seen = []
    t = 0.0
    while not s.done:
        for f in drain(s, t):
            seen.append(f.seq)
            s.on_transmitted(f.seq, t)
            s.on_ack(Ack.from_frame(r.on_data(f)), t)
            t += 0.1
    assert r.payloads == s.payloads
    assert seen == [i % 16 for i in range(40)]
    assert s.retransmissions == 0


def test_lost_frame_goes_back_to_base() -> None:
    s, r = mk(window=4), GbnReceiver(7)
    frames = drain(s, 0)
    for f in frames:
        s.on_transmitted(f.seq, 0)
    acks = [r.on_data(f) for f in frames if f.seq != 1]
    assert [a.ack for a in acks] == [1, 1, 1]
    assert r.discarded == 2
    for a in acks:
        s.on_ack(Ack.from_frame(a), 0.2)
    assert s.base == 1
    assert [f.seq for f in drain(s, 0.5)] == [4]
    assert drain(s, 1.1) == []
    assert [f.seq for f in drain(s, 1.2)] == [1, 2, 3, 4]
    assert s.retransmissions == 4
    assert s.timeouts == 1


def test_lost_ack_is_covered_by_cumulative_ack() -> None:
    s, r = mk(window=4), GbnReceiver(7)
    acks = [r.on_data(f) for f in drain(s, 0)]
    assert s.on_ack(Ack.from_frame(acks[-1]), 0)
    assert s.base == 4


def test_timer_starts_when_base_is_transmitted() -> None:
    s = mk(timeout=1.0)
    drain(s, 0)
    assert s.next_deadline() is None
    s.on_transmitted(1, 3.0)
    assert s.next_deadline() is None
    s.on_transmitted(0, 5.0)
    assert s.next_deadline() == 6.0


def test_ack_advance_restarts_or_stops_timer() -> None:
    s = mk(n=2, window=4, timeout=1.0)
    drain(s, 0)
    s.on_transmitted(0, 0)
    s.on_ack(ack(1), 0.5)
    assert s.next_deadline() == 1.5
    s.on_ack(ack(2), 0.7)
    assert s.done and s.next_deadline() is None


def test_ignores_foreign_duplicate_and_out_of_range_acks() -> None:
    s = mk(window=4)
    drain(s, 0)
    assert not s.on_ack(Ack(99, 2), 0)
    assert not s.on_ack(ack(0), 0)
    assert not s.on_ack(ack(9), 0)
    assert s.base == 0


def test_fails_after_max_retries() -> None:
    s = mk(window=2, timeout=1.0, max_retries=2)
    t = 0.0
    for _ in range(3):
        frames = drain(s, t)
        assert frames
        s.on_transmitted(frames[0].seq, t)
        t += 1.0
    assert drain(s, t) == []
    assert s.failed and s.timeouts == 3
    assert s.next_deadline() is None


def test_receiver_repeats_ack_for_duplicates_and_out_of_order() -> None:
    r = GbnReceiver(7)
    assert r.on_data(Frame.data(0, b"a")).ack == 1
    assert r.on_data(Frame.data(0, b"a")).ack == 1
    assert r.on_data(Frame.data(5, b"x")).ack == 1
    assert r.payloads == [b"a"] and r.discarded == 2


def test_invalid_window() -> None:
    with pytest.raises(ValueError):
        GbnSender(1, [], 16, 1.0)


def test_timing_helpers() -> None:
    assert frame_time(900, 9600, True) == pytest.approx(2 * frame_time(900, 19200, True))
    assert frame_time(900, 9600, True) > frame_time(900, 9600, False)
    assert suggest_timeout(9600, 900, True) > frame_time(900, 9600, True)
