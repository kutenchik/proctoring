"""Named camera capture using the SAME Qt device ID as the setup selector."""
from PySide6.QtCore import QEventLoop, QThread, QTimer, Qt
from .camera import LatestFrameCamera, CapturedFrame


class CameraThread(QThread):
    def __init__(self, camera):
        super().__init__()
        self.camera = camera

    def run(self):
        self.camera._run_qt()


class NamedCamera(LatestFrameCamera):
    def __init__(self, config, clock, device_id):
        super().__init__(config, clock)
        self.device_id = device_id
        self._backend = 'qt-device-id'

    @property
    def alive(self):
        return bool(self._thread and self._thread.isRunning())

    def start(self):
        if self.alive:
            return
        if self.stopped:
            raise RuntimeError('Stopped camera cannot be reopened')
        self._thread = CameraThread(self)
        self._thread.start()

    def stop(self, timeout=.5):
        self._stop.set()
        with self._lock:
            self._latest = None
        if self._thread and QThread.currentThread() is not self._thread:
            self._thread.wait(round(max(0., timeout) * 1000))

    def _accept_image(self, image):
        import numpy as np
        from PySide6.QtGui import QImage
        if image.isNull() or self.stopped:
            return
        rgb = image.convertToFormat(QImage.Format.Format_RGB888)
        pixels = np.frombuffer(rgb.bits(), np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
        bgr = pixels[:, :rgb.width()*3].reshape(rgb.height(), rgb.width(), 3)[:, :, ::-1].copy()
        now = self.clock.monotonic()
        with self._lock:
            if self.stopped:
                return
            self._sequence += 1
            self._latest = CapturedFrame(self._sequence, now, bgr)
            self._times.append(now)
            self._heartbeat = now
            self._error = self._error_at = None

    def _run_qt(self):
        camera = session = sink = None
        try:
            from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
            device = next((d for d in QMediaDevices.videoInputs()
                           if bytes(d.id()).hex() == self.device_id), None)
            if device is None:
                raise RuntimeError('Selected camera unavailable; choose another camera')
            camera = QCamera(device)
            formats = device.videoFormats()
            if formats:
                preferred = min(formats, key=lambda f: (
                    abs(f.resolution().width()-self.config.capture_width) +
                    abs(f.resolution().height()-self.config.capture_height),
                    abs(f.maxFrameRate()-self.config.capture_fps)))
                camera.setCameraFormat(preferred)
            session, sink = QMediaCaptureSession(), QVideoSink()
            session.setCamera(camera)
            session.setVideoSink(sink)
            loop = QEventLoop()
            def received(frame):
                try:
                    self._accept_image(frame.toImage())
                except Exception:
                    self._fail('Camera frame conversion failed; retry camera')
                    loop.quit()
            def failed(*_):
                self._fail('Camera unavailable: check permissions, connection or another app using it')
                loop.quit()
            sink.videoFrameChanged.connect(received, Qt.ConnectionType.DirectConnection)
            camera.errorOccurred.connect(failed)
            start = self.clock.monotonic()
            def check():
                if self.stopped:
                    loop.quit()
                # A reopened same-source capture retains the outage timestamp
                # and old heartbeat, but gets its own first-frame open grace.
                elif self.clock.monotonic() - max(start, self.heartbeat or start) > 10.:
                    self._fail('Camera frames stopped; reconnect and retry camera')
                    loop.quit()
            timer = QTimer()
            timer.timeout.connect(check)
            timer.start(100)
            if not self.stopped:
                camera.start()
                loop.exec()
            timer.stop()
        except Exception as error:
            self._fail(str(error))
        finally:
            if camera is not None:
                camera.stop()
            if session is not None:
                session.setVideoSink(None)
                session.setCamera(None)
            # Native resources are destroyed on their owning capture thread.
            del sink, session, camera
