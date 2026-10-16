"""Run with the existing Python environment; stdin/stdout are control only."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time

from .protocol import MAX_REQUEST_BYTES, Protocol
from .diagnostics import emit


class ControlTransport:
    def __init__(self, input_stream, output_stream):
        self.input, self.output = input_stream, output_stream
        self.incoming = queue.Queue(maxsize=64)
        self.outgoing = queue.Queue(maxsize=128)
        self.disconnected = threading.Event()
        self._writer = threading.Thread(target=self._write, name='desktop-control-output', daemon=True)
        self._reader = threading.Thread(target=self._read, name='desktop-control-input', daemon=True)

    def start(self):
        self._writer.start()
        self._reader.start()

    def _read(self):
        pending = b''
        try:
            while not self.disconnected.is_set():
                chunk = self.input.read(4096)
                if not chunk:
                    break
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if len(line)+1 > MAX_REQUEST_BYTES:
                        return
                    self.incoming.put_nowait(line+b'\n')
                if len(pending) >= MAX_REQUEST_BYTES:
                    return  # Never accumulate an unbounded unterminated frame.
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            self.disconnected.set()

    def send(self, response):
        try:
            self.outgoing.put_nowait(json.dumps(response, allow_nan=False, separators=(',', ':')).encode('utf-8')+b'\n')
        except (ValueError, queue.Full):
            self.disconnected.set()

    def _write(self):
        try:
            while True:
                data = self.outgoing.get()
                if data is None:
                    return
                remaining = memoryview(data)
                while remaining:
                    written = self.output.write(remaining)
                    if not written:
                        raise OSError('Parent control pipe disconnected')
                    remaining = remaining[written:]
                self.output.flush()
        except (OSError, ValueError):
            self.disconnected.set()

    def close(self):
        self.disconnected.set()
        try:
            self.outgoing.put_nowait(None)
        except queue.Full:
            pass
        self._writer.join(.2)


class ShutdownDrain:
    """Keep Qt alive briefly while a report worker releases its Qt objects."""
    def __init__(self, bridge, *, monotonic=time.monotonic, timeout=1.):
        self.bridge, self.monotonic, self.timeout = bridge, monotonic, timeout
        self.started = None

    def begin(self):
        if self.started is None:
            self.bridge.close()
            self.started = self.monotonic()

    def finished(self):
        if self.started is None:
            return False
        elapsed = self.monotonic()-self.started
        # Let the final control response flush before an otherwise immediate exit.
        return elapsed >= .05 and (not self.bridge.report_cleanup_pending or elapsed >= self.timeout)


def main(argv=None):
    from .supervisor import announce_backend_identity
    announce_backend_identity()
    parser = argparse.ArgumentParser(description='Local Proctoring desktop workflow bridge')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--preview-pipe')
    parser.add_argument('--preview-token')
    args = parser.parse_args(argv)
    if bool(args.preview_pipe) != bool(args.preview_token):
        parser.error('--preview-pipe and --preview-token must be supplied together')
    if args.preview_pipe and not re.fullmatch(r'\\\\\.\\pipe\\local-proctoring-[A-Za-z0-9-]{8,100}', args.preview_pipe):
        parser.error('Preview pipe must use the reserved local-proctoring namespace')
    if args.preview_token and not re.fullmatch(r'[a-fA-F0-9]{64}', args.preview_token):
        parser.error('Preview token must be 64 hexadecimal characters')
    control_output = getattr(sys.stdout.buffer, 'raw', sys.stdout.buffer)
    sys.stdout = sys.stderr  # Third-party Python logging cannot corrupt NDJSON.
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QTimer
    from ..config import load_config
    from .workflow import WorkflowBridge
    from .preview import LatestPreview
    app = QGuiApplication.instance() or QGuiApplication(['local-proctoring-desktop-bridge'])
    try:
        config = load_config(args.config)
    except Exception:
        print('Unable to load desktop configuration; check the configured TOML path.', file=sys.stderr)
        return 2
    try:
        bridge = WorkflowBridge(config, expected_launch_id=os.environ.get('PROCTORING_HOST_LAUNCH_ID'),
                                package_root=os.environ.get('PROCTORING_PACKAGE_ROOT'))
    except Exception:
        print('ELECTRON_HOST_UNAVAILABLE: A verified Electron host launch is required for protected mode.', file=sys.stderr)
        return 2
    if args.preview_pipe:
        bridge.preview = LatestPreview(args.preview_pipe, args.preview_token, bridge.clock, bridge.latest_frame)
    # A daemon blocked inside BufferedReader.readline holds its Python I/O lock
    # across shutdown. The raw pipe avoids that fatal interpreter-finalize race.
    transport = ControlTransport(getattr(sys.stdin.buffer, 'raw', sys.stdin.buffer), control_output)
    protocol = Protocol(bridge.dispatch)
    exiting = False
    last_control_at = bridge.clock.monotonic()
    shutdown = ShutdownDrain(bridge)

    def tick():
        nonlocal exiting, last_control_at
        if exiting:
            if shutdown.finished():
                app.quit()
            return
        if transport.disconnected.is_set():
            emit('backend_transport_closed')
            exiting = True
            shutdown.begin()
            return
        if (bridge.controller.session.started or bridge.consent) and bridge.clock.monotonic()-last_control_at > 3.:
            bridge.dispatch('presentation.lost', {})
        bridge.tick()
        for _ in range(4):
            try:
                raw = transport.incoming.get_nowait()
            except queue.Empty:
                break
            transport.send(protocol.handle(raw))
            last_control_at = bridge.clock.monotonic()
            if bridge.closed:
                exiting = True
                shutdown.begin()
                return

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)
    app.aboutToQuit.connect(bridge.close)
    transport.start()
    emit('backend_ready')
    try:
        return app.exec()
    finally:
        timer.stop()
        emit('backend_shutdown')
        bridge.close()
        transport.close()
        if bridge.report_cleanup_pending:
            # Do not destroy QGuiApplication under a worker still using fonts or
            # QPdfWriter. The existing atomic PDF remains unavailable, while the
            # already-finalized local summary/journal remain intact.
            print('PDF_INTERRUPTED: Report generation exceeded shutdown grace; local session records were saved.',
                  file=sys.stderr, flush=True)
            os._exit(4)
        if bridge.native_cleanup_pending:
            # A wedged driver cannot be destroyed safely by Qt/Python finalizers.
            # Process termination releases its handles; tell the parent this was
            # not a clean shutdown. Never restart the devices automatically.
            print('Device cleanup exceeded two seconds; closing the desktop process.', file=sys.stderr, flush=True)
            os._exit(3)


if __name__ == '__main__':
    raise SystemExit(main())
