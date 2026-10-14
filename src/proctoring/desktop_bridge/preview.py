"""Pull-only, one-frame named-pipe transport; preview pixels never touch disk."""
import base64
import json
import os
import struct
import threading

MAX_JPEG_BYTES = 512 * 1024
MAX_PACKET_BYTES = 720 * 1024
MAX_EDGE = 960


def encode_frame(frame):
    import cv2
    height, width = frame.image.shape[:2]
    scale = min(1., MAX_EDGE / max(width, height))
    preview = frame.image
    if scale < 1:
        preview = cv2.resize(preview, (max(1, round(width*scale)), max(1, round(height*scale))),
                             interpolation=cv2.INTER_AREA)
    for quality in (78, 60, 40):
        success, image = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if success and image.nbytes <= MAX_JPEG_BYTES:
            return {'sequence': frame.sequence, 'captured_at': frame.timestamp,
                    'source_width': width, 'source_height': height,
                    'width': preview.shape[1], 'height': preview.shape[0],
                    'mime': 'image/jpeg', 'overlays': list(getattr(frame, 'overlays', ())),
                    'jpeg_base64': base64.b64encode(image).decode('ascii')}
    raise ValueError('Preview cannot fit within the bounded JPEG transport')


def _write_all(stream, value):
    remaining = memoryview(value)
    while remaining:
        count = stream.write(remaining)
        if count is None or count <= 0:
            raise OSError('Preview pipe disconnected')
        remaining = remaining[count:]


class LatestPreview:
    """One decoder request, one encoder, one write; no queue of old frames."""
    def __init__(self, pipe, token, clock, frame_provider, *, encoder=encode_frame, connector=None):
        self.pipe, self.token = pipe, token
        self.clock, self.frame_provider, self.encoder = clock, frame_provider, encoder
        self.connector = connector or self._connect
        self._stop = threading.Event()
        self._stream = None
        self._last_submitted = None
        self._generation = 0
        self.metadata = None
        self.error = None
        self._thread = threading.Thread(target=self._run, name='desktop-preview', daemon=True)
        self._thread.start()

    def _connect(self):
        if os.name != 'nt':
            raise OSError('Windows named pipes are required for native preview')
        return open(self.pipe, 'r+b', buffering=0)

    def clear(self):
        self._generation += 1
        self.metadata = None
        self._last_submitted = None

    def _run(self):
        try:
            with self.connector() as stream:
                self._stream = stream
                _write_all(stream, json.dumps({'token': self.token}, separators=(',', ':')).encode()+b'\n')
                while not self._stop.is_set():
                    command = stream.read(1)
                    if command != b'\x01':
                        return
                    now = self.clock.monotonic()
                    frame = self.frame_provider()
                    if (frame is None or now-frame.timestamp < 0 or now-frame.timestamp > 2. or
                            (self._last_submitted is not None and now-self._last_submitted < .125) or
                            (self.metadata is not None and frame.sequence == self.metadata['sequence'])):
                        _write_all(stream, struct.pack('>I', 0))
                        continue
                    self._last_submitted = now
                    generation = self._generation
                    packet = self.encoder(frame)
                    encoded = json.dumps(packet, allow_nan=False, separators=(',', ':')).encode('utf-8')
                    if len(encoded) > MAX_PACKET_BYTES:
                        raise ValueError('Preview packet exceeded its bound')
                    # Stop/change during encoding cannot publish the old frame.
                    current = self.frame_provider()
                    if self._stop.is_set():
                        return
                    if (generation != self._generation or current is None or
                            current.sequence < frame.sequence or current.timestamp < frame.timestamp):
                        _write_all(stream, struct.pack('>I', 0))
                        continue
                    _write_all(stream, struct.pack('>I', len(encoded))+encoded)
                    self.metadata = {key: value for key, value in packet.items() if key != 'jpeg_base64'}
        except Exception:
            self.error = 'Camera preview connection unavailable; restart the desktop bridge'
        finally:
            self._stream = None

    def close(self):
        self._stop.set()
        # A stalled consumer must not delay control/device shutdown. The process
        # supervisor closes its pipe; this daemon may be blocked on its final write.
        self.clear()
