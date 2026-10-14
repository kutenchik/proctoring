"""Preview packets remain bounded, latest-only, and independent of controls."""
import base64
import json
import struct
import threading

import numpy as np

from proctoring.clock import FakeClock
from proctoring.desktop_bridge.preview import LatestPreview, MAX_JPEG_BYTES, MAX_PACKET_BYTES, encode_frame
from proctoring.vision.camera import CapturedFrame


class Pipe:
    def __init__(self, count=1, on_read=None):
        self.count, self.on_read = count, on_read
        self.parts = []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size):
        assert size == 1
        if self.count <= 0:
            return b''
        self.count -= 1
        if self.on_read:
            self.on_read()
        return b'\x01'
    def write(self, value):
        self.parts.append(bytes(value))
        return len(value)
    def packets(self):
        raw = b''.join(self.parts)
        auth, rest = raw.split(b'\n', 1)
        result = []
        while rest:
            size = struct.unpack('>I', rest[:4])[0]
            result.append(json.loads(rest[4:4+size]) if size else None)
            rest = rest[4+size:]
        return json.loads(auth), result


def frame(sequence=1, timestamp=10., shape=(480, 640, 3)):
    return CapturedFrame(sequence, timestamp, np.zeros(shape, dtype=np.uint8))


def test_encoding_preserves_source_dimensions_timestamp_and_scales_only_preview():
    import cv2
    source = frame(shape=(2160, 3840, 3))
    packet = encode_frame(source)
    data = base64.b64decode(packet['jpeg_base64'])
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert len(data) <= MAX_JPEG_BYTES
    assert decoded.shape == (540, 960, 3)
    assert (packet['source_width'], packet['source_height']) == (3840, 2160)
    assert packet['sequence'] == 1 and packet['captured_at'] == 10.
    assert packet['overlays'] == []


def test_pipe_authentication_and_latest_frame_are_one_matching_packet():
    clock, stream = FakeClock(10.), Pipe()
    source = frame(42)
    preview = LatestPreview('unused', 'a'*64, clock, lambda: source, connector=lambda: stream)
    preview._thread.join(2.)
    auth, packets = stream.packets()
    assert auth == {'token': 'a'*64}
    assert len(packets) == 1 and packets[0]['sequence'] == 42
    assert packets[0]['captured_at'] == source.timestamp
    assert len(json.dumps(packets[0]).encode()) <= MAX_PACKET_BYTES
    assert 'jpeg_base64' not in preview.metadata


def test_preview_rate_bounded_and_no_unsolicited_frame_encoding():
    clock, stream = FakeClock(10.), Pipe(20)
    calls = []
    def encode(source):
        calls.append(source.sequence)
        return encode_frame(source)
    preview = LatestPreview('unused', 'a'*64, clock, lambda: frame(), encoder=encode, connector=lambda: stream)
    preview._thread.join(2.)
    _, packets = stream.packets()
    assert calls == [1] and len(packets) == 20 and packets[1:] == [None]*19


def test_missing_or_stale_frame_never_reuses_previous_pixels():
    clock, stream = FakeClock(13.), Pipe(2)
    preview = LatestPreview('unused', 'a'*64, clock, lambda: frame(), connector=lambda: stream)
    preview._thread.join(2.)
    assert stream.packets()[1] == [None, None] and preview.metadata is None


def test_clear_during_encoding_discards_inflight_frame():
    entered, release = threading.Event(), threading.Event()
    stream, clock = Pipe(), FakeClock(10.)
    def encode(source):
        entered.set()
        assert release.wait(2.)
        return encode_frame(source)
    preview = LatestPreview('unused', 'a'*64, clock, lambda: frame(), encoder=encode, connector=lambda: stream)
    assert entered.wait(1.)
    preview.clear()
    release.set()
    preview._thread.join(2.)
    assert stream.packets()[1] == [None] and preview.metadata is None


def test_preview_backpressure_does_not_block_shutdown():
    entered, release = threading.Event(), threading.Event()
    class StalledPipe(Pipe):
        def write(self, data):
            if self.parts:
                entered.set()
                assert release.wait(2.)
            return super().write(data)
    stream = StalledPipe()
    preview = LatestPreview('unused', 'a'*64, FakeClock(10.), lambda: frame(), connector=lambda: stream)
    assert entered.wait(1.)
    preview.close()  # Must not join the blocked writer or delay device cleanup.
    assert preview._stop.is_set()
    release.set()
    preview._thread.join(2.)


def test_oversized_packet_and_broken_pipe_fail_explicitly():
    stream = Pipe()
    preview = LatestPreview('unused', 'a'*64, FakeClock(10.), lambda: frame(),
                            encoder=lambda _: {'jpeg_base64': 'x'*(MAX_PACKET_BYTES+1)}, connector=lambda: stream)
    preview._thread.join(2.)
    assert preview.error is not None and stream.packets()[1] == []
    def broken():
        raise OSError('failure')
    preview = LatestPreview('unused', 'a'*64, FakeClock(10.), lambda: frame(), connector=broken)
    preview._thread.join(2.)
    assert preview.error is not None
