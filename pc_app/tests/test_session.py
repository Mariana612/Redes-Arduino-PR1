import random

from redes_arduino.frame import Frame, FrameType
from redes_arduino.messages import FileType, Fin
from redes_arduino.monitor import Phase
from redes_arduino.session import Endpoint, LinkConfig
from redes_arduino.simchannel import SimLink

CFG = LinkConfig(payload_size=500, window=4)
DATA = random.Random(5).randbytes(3_000)


def lose(kind: FrameType, src: str, times: int = 1) -> tuple[list[Frame], object]:
    sent: list[Frame] = []
    left = [times]

    def drop(name: str, fr: Frame) -> bool:
        sent.append(fr)
        if name == src and fr.type is kind and left[0] > 0:
            left[0] -= 1
            return True
        return False

    return sent, drop


def run(drop: object = None, a_cfg: LinkConfig = CFG, b_cfg: LinkConfig = CFG):  # type: ignore[no-untyped-def]
    a, b = Endpoint("A", a_cfg), Endpoint("B", b_cfg)
    s = a.send_file(DATA, FileType.TXT, 42, timeout=1.0, max_retries=3)
    SimLink(a, b, drop=drop).run()  # type: ignore[arg-type]
    return s, a, b


def test_happy_path() -> None:
    s, _, b = run()
    assert s.phase is Phase.DONE and s.progress == 1.0
    assert b.receiver.phase is Phase.DONE
    assert b.receiver.data == DATA


def test_incompatible_parameters_rejected() -> None:
    s, _, b = run(b_cfg=LinkConfig(payload_size=500, window=8))
    assert s.phase is Phase.FAILED
    assert s.error is not None and "INCOMPATIBLE_PARAMS" in s.error
    assert b.receiver.phase is Phase.IDLE


def test_lost_start_is_retransmitted() -> None:
    _, drop = lose(FrameType.START, "A")
    s, _, b = run(drop)
    assert s.phase is Phase.DONE and s.control_retransmissions == 1
    assert b.receiver.data == DATA


def test_lost_start_ack_does_not_duplicate_transfer() -> None:
    sent, drop = lose(FrameType.START_ACK, "B")
    s, _, b = run(drop)
    assert s.phase is Phase.DONE
    assert sum(f.type is FrameType.START for f in sent) == 2
    assert sum(f.type is FrameType.START_ACK for f in sent) == 2
    assert b.receiver.data == DATA


def test_lost_fin_ack_answered_from_cache() -> None:
    sent, drop = lose(FrameType.FIN_ACK, "B")
    s, _, b = run(drop)
    assert s.phase is Phase.DONE
    assert sum(f.type is FrameType.FIN for f in sent) == 2
    assert b.receiver.phase is Phase.DONE


def test_hash_mismatch_fails_both_sides() -> None:
    a, b = Endpoint("A", CFG), Endpoint("B", CFG)
    s = a.send_file(DATA, FileType.TXT, 42, timeout=1.0)
    s._fin = Fin(42, bytes(32)).to_frame()
    SimLink(a, b).run()
    assert s.phase is Phase.FAILED and s.error is not None and "HASH_MISMATCH" in s.error
    assert b.receiver.phase is Phase.FAILED and b.receiver.data is None


def test_start_never_answered_aborts() -> None:
    sent, drop = lose(FrameType.START, "A", times=99)
    s, _, _ = run(drop)
    assert s.phase is Phase.FAILED
    assert s.control_retransmissions == 3
    assert sent[-1].type is FrameType.ABORT


def test_gbn_failure_sends_abort_to_receiver() -> None:
    def drop(name: str, fr: Frame) -> bool:
        return fr.type is FrameType.DATA and fr.seq == 2

    s, _, b = run(drop)
    assert s.phase is Phase.FAILED and s.gbn.failed
    assert b.receiver.phase is Phase.FAILED
    assert b.receiver.error is not None and "MAX_RETRIES" in b.receiver.error


def test_empty_file() -> None:
    a, b = Endpoint("A", CFG), Endpoint("B", CFG)
    s = a.send_file(b"", FileType.TXT, 1, timeout=1.0)
    assert SimLink(a, b).run()
    assert s.phase is Phase.DONE and b.receiver.data == b""


def test_receiver_busy_rejects_second_transfer() -> None:
    a, b = Endpoint("A", CFG), Endpoint("B", CFG)
    a.send_file(DATA, FileType.TXT, 1)
    link = SimLink(a, b)
    link.run(until=0.5)
    assert b.receiver.phase is Phase.TRANSFERRING
    from redes_arduino.messages import Speed, Start, StartAck, StartStatus

    other = Start(2, 10, FileType.TXT, Speed.BPS_9600, 500, 4, True).to_frame()
    reply = b.receiver.on_frame(other)
    assert reply is not None
    assert StartAck.from_payload(reply.payload).status is StartStatus.BUSY
